# src/palatium_ai/application/services/memory_recall.py

"""Budgeted search over MemoryPort for the hot path."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.memory.scratchpad import SessionScratchpad

logger = get_logger(__name__)

_DEFAULT_LIMIT = 4
_DEFAULT_MAX_CHARS = 800
# Platform confidence gate: low-quality memory is worse than none (LongMemEval).
_DEFAULT_MIN_CONFIDENCE = 0.7


async def recall_for_thread(
    memory_port: MemoryPort | None,
    *,
    thread_id: str,
    query: str,
    user_id: str | None = None,
    org_id: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    max_chars: int = _DEFAULT_MAX_CHARS,
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    scratchpad: SessionScratchpad | None = None,
) -> MemoryRecallBundle:
    """Pin scratchpad slots first, then durable search; drop low-confidence durable hits."""
    pinned = list(scratchpad.as_memory_hits()) if scratchpad is not None else []
    if memory_port is None or not query.strip():
        return _bundle(thread_id, pinned, limit=limit, max_chars=max_chars)

    raw = await _search_namespaces(
        memory_port,
        namespaces=_recall_namespaces(thread_id, user_id=user_id, org_id=org_id),
        query=query,
        overfetch=max(limit * 3, 8),
    )
    durable = await _select_durable_hits(
        memory_port,
        raw,
        pinned=pinned,
        limit=limit,
        min_confidence=min_confidence,
    )
    return _bundle(thread_id, pinned + durable, limit=limit, max_chars=max_chars)


def _recall_namespaces(
    thread_id: str,
    *,
    user_id: str | None,
    org_id: str | None,
) -> list[tuple[str, ...]]:
    namespaces: list[tuple[str, ...]] = [thread_namespace(thread_id)]
    if user_id and user_id.strip():
        namespaces.append(user_namespace(user_id.strip()))
    if org_id and org_id.strip():
        namespaces.append(org_namespace(org_id.strip()))
    return namespaces


async def _search_namespaces(
    memory_port: MemoryPort,
    *,
    namespaces: list[tuple[str, ...]],
    query: str,
    overfetch: int,
) -> list[tuple[tuple[str, ...], dict[str, object]]]:
    raw: list[tuple[tuple[str, ...], dict[str, object]]] = []
    for namespace in namespaces:
        raw.extend(
            (namespace, item) for item in await memory_port.search(namespace=namespace, query=query, limit=overfetch)
        )
    return raw


async def _select_durable_hits(
    memory_port: MemoryPort,
    raw: list[tuple[tuple[str, ...], dict[str, object]]],
    *,
    pinned: list[MemoryHit],
    limit: int,
    min_confidence: float,
) -> list[MemoryHit]:
    durable: list[MemoryHit] = []
    seen_texts: set[str] = {hit.text.strip().lower() for hit in pinned if hit.text.strip()}
    bump = getattr(memory_port, "bump_access", None)
    ranked = sorted(raw, key=lambda pair: _item_score(pair[1]), reverse=True)
    for idx, (namespace, item) in enumerate(ranked):
        hit = _durable_hit_from_item(item, idx=idx, limit=limit, min_confidence=min_confidence, seen=seen_texts)
        if hit is None:
            continue
        seen_texts.add(hit.text.lower())
        durable.append(hit)
        await _maybe_bump_access(bump, namespace=namespace, item=item)
        if len(pinned) + len(durable) >= limit:
            break
    return durable


def _durable_hit_from_item(
    item: dict[str, object],
    *,
    idx: int,
    limit: int,
    min_confidence: float,
    seen: set[str],
) -> MemoryHit | None:
    if str(item.get("kind", "")).strip().lower() == "scratchpad":
        return None
    text = str(item.get("text", "")).strip()
    if not text or text.lower() in seen:
        return None
    confidence = max(0.0, min(1.0, coerce_float(item.get("confidence", 0.0))))
    if confidence < min_confidence:
        return None
    score_f = _item_score(item)
    score = max(0, int(score_f * 100) if score_f else max(0, limit - idx))
    return MemoryHit(
        text=text[:2000],
        kind=str(item.get("kind", "fact"))[:32],
        confidence=confidence,
        score=score,
    )


async def _maybe_bump_access(
    bump: Callable[..., object] | None,
    *,
    namespace: tuple[str, ...],
    item: dict[str, object],
) -> None:
    entry_key = str(item.get("_entry_key", "")).strip()
    if not entry_key or not callable(bump):
        return
    try:
        await bump(namespace=namespace, key=entry_key)  # type: ignore[misc]  # bump — inspect-вызов, точный тип недоступен (017)
    except Exception as exc:
        logger.warning(
            "memory_recall.bump_access_failed",
            entry_key=entry_key,
            error=str(exc),
        )


def _bundle(
    thread_id: str,
    hits: list[MemoryHit],
    *,
    limit: int,
    max_chars: int,
) -> MemoryRecallBundle:
    return MemoryRecallBundle(
        thread_id=thread_id,
        hits=tuple(hits[:limit]),
        max_items=limit,
        max_chars=max_chars,
    )


def _item_score(item: dict[str, object]) -> float:
    return coerce_float(item.get("_score", 0.0) or 0.0)
