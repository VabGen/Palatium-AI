# src/palatium_ai/application/services/memory_recall.py

"""Budgeted search over MemoryPort (+ optional L4 graph) for the hot path."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle
from palatium_ai.domain.memory.scoring import (
    ImportanceInputs,
    compute_importance,
    lexical_relevance,
    recency_score,
)

if TYPE_CHECKING:
    from palatium_ai.domain.graph.write_port import GraphFactRecord, GraphWritePort
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.memory.scratchpad import SessionScratchpad

logger = get_logger(__name__)

_DEFAULT_LIMIT = 4
_DEFAULT_MAX_CHARS = 800
# Platform confidence gate: low-quality memory is worse than none (LongMemEval).
_DEFAULT_MIN_CONFIDENCE = 0.7
_GRAPH_OVERFETCH = 3
# Preferences shape *how* to answer regardless of the ask; facts must match the ask.
_QUERY_INDEPENDENT_KINDS = frozenset({"preference"})
# Hot-path Select: user_namespace is profile prefs only (060). Cross-thread
# fact/episode/incident bleed (P0-B / A.2d) must not enter memory_hits.
_USER_NS_HOT_PATH_KINDS = frozenset({"preference"})


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
    kinds: tuple[str, ...] | None = None,
    graph_write: GraphWritePort | None = None,
    as_of: datetime | None = None,
) -> MemoryRecallBundle:
    """Pin scratchpad slots first, then durable medium + active L4 facts.

    ``kinds`` optionally restricts durable hits to MemoryType values (e.g. preference
    for capability_discovery). Scratchpad pins are never filtered by kind.
    ``as_of`` pins the bi-temporal view of L4 (default: now, UTC) so every recall in
    one turn sees the same graph snapshot.
    """
    pinned = [
        MemoryHit(
            text=h.text,
            kind=h.kind,
            confidence=h.confidence,
            score=h.score,
            source="scratchpad",
        )
        for h in (scratchpad.as_memory_hits() if scratchpad is not None else [])
    ]
    if not query.strip():
        if pinned:
            agent_metrics.record_memory_recall_source(source="scratchpad")
        else:
            agent_metrics.record_memory_recall_source(source="empty")
        return _bundle(thread_id, pinned, limit=limit, max_chars=max_chars)

    durable: list[MemoryHit] = []
    if memory_port is not None:
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
            kinds=kinds,
        )
    graph_hits = await _select_graph_hits(
        graph_write,
        user_id=user_id,
        thread_id=thread_id,
        query=query,
        pinned=pinned,
        durable=durable,
        limit=limit,
        min_confidence=min_confidence,
        kinds=kinds,
        as_of=as_of,
    )
    merged = pinned + durable + graph_hits
    _record_recall_sources(pinned=pinned, durable=durable, graph_hits=graph_hits)
    return _bundle(thread_id, merged, limit=limit, max_chars=max_chars)


def _record_recall_sources(
    *,
    pinned: list[MemoryHit],
    durable: list[MemoryHit],
    graph_hits: list[MemoryHit],
) -> None:
    if pinned:
        agent_metrics.record_memory_recall_source(source="scratchpad")
    if durable:
        agent_metrics.record_memory_recall_source(source="medium")
    if graph_hits:
        agent_metrics.record_memory_recall_source(source="graph")
    if not pinned and not durable and not graph_hits:
        agent_metrics.record_memory_recall_source(source="empty")


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
    async def _one(namespace: tuple[str, ...]) -> list[tuple[tuple[str, ...], dict[str, object]]]:
        items = await memory_port.search(namespace=namespace, query=query, limit=overfetch)
        return [(namespace, item) for item in items]

    batches = await asyncio.gather(*(_one(ns) for ns in namespaces))
    raw: list[tuple[tuple[str, ...], dict[str, object]]] = []
    for batch in batches:
        raw.extend(batch)
    return raw


async def _select_durable_hits(
    memory_port: MemoryPort,
    raw: list[tuple[tuple[str, ...], dict[str, object]]],
    *,
    pinned: list[MemoryHit],
    limit: int,
    min_confidence: float,
    kinds: tuple[str, ...] | None = None,
) -> list[MemoryHit]:
    durable: list[MemoryHit] = []
    seen_texts: set[str] = {hit.text.strip().lower() for hit in pinned if hit.text.strip()}
    allowed_kinds = {k.strip().lower() for k in kinds} if kinds else None
    bump = getattr(memory_port, "bump_access", None)
    ranked = sorted(raw, key=lambda pair: _item_score(pair[1]), reverse=True)
    for idx, (namespace, item) in enumerate(ranked):
        if _is_user_namespace(namespace):
            kind = str(item.get("kind", "fact")).strip().lower() or "fact"
            if kind not in _USER_NS_HOT_PATH_KINDS:
                continue
        hit = _durable_hit_from_item(
            item,
            idx=idx,
            limit=limit,
            min_confidence=min_confidence,
            seen=seen_texts,
            allowed_kinds=allowed_kinds,
        )
        if hit is None:
            continue
        seen_texts.add(hit.text.lower())
        durable.append(hit)
        # Reconsolidation on recall (060): bump access_frequency + last_accessed.
        await _maybe_bump_access(bump, namespace=namespace, item=item)
        if len(pinned) + len(durable) >= limit:
            break
    return durable


def _is_user_namespace(namespace: tuple[str, ...]) -> bool:
    return bool(namespace) and namespace[0] == "user"


async def _select_graph_hits(
    graph_write: GraphWritePort | None,
    *,
    user_id: str | None,
    thread_id: str,
    query: str,
    pinned: list[MemoryHit],
    durable: list[MemoryHit],
    limit: int,
    min_confidence: float,
    kinds: tuple[str, ...] | None,
    as_of: datetime | None,
) -> list[MemoryHit]:
    """Budgeted L4 facts active at ``as_of`` (bi-temporal), fused after medium (SB3)."""
    if graph_write is None or not user_id or not user_id.strip():
        return []
    remaining = max(0, limit - len(pinned) - len(durable))
    if remaining <= 0:
        return []
    try:
        records = await graph_write.list_active_facts(
            user_id=user_id.strip(),
            limit=max(remaining * _GRAPH_OVERFETCH, remaining),
            as_of=as_of,
            thread_id=thread_id,
        )
    except Exception as exc:  # noqa: BLE001  # graph select failure degrades to medium-only recall (060)
        logger.warning("memory_recall.graph_select_failed", error=str(exc))
        return []
    seen = {h.text.strip().lower() for h in pinned + durable if h.text.strip()}
    allowed_kinds = {k.strip().lower() for k in kinds} if kinds else None
    moment = _aware(as_of) if as_of is not None else datetime.now(UTC)
    candidates: list[MemoryHit] = []
    for rec in records:
        hit = _graph_hit(
            rec,
            query=query,
            as_of=moment,
            seen=seen,
            allowed_kinds=allowed_kinds,
            min_confidence=min_confidence,
        )
        if hit is not None:
            seen.add(hit.text.lower())
            candidates.append(hit)
    candidates.sort(key=lambda hit: hit.score, reverse=True)
    return candidates[:remaining]


def _graph_hit(
    rec: GraphFactRecord,
    *,
    query: str,
    as_of: datetime,
    seen: set[str],
    allowed_kinds: set[str] | None,
    min_confidence: float,
) -> MemoryHit | None:
    """Graph fact → hit, ranked by the 060.2 importance formula at ``as_of``.

    Query-independent preferences always qualify; other facts need lexical overlap
    with the current ask so a promoted fact from an unrelated task does not ride
    into this turn on stored importance alone.
    """
    text = (rec.text or "").strip()
    if not text or text.lower() in seen:
        return None
    kind = (rec.kind or "fact").strip().lower() or "fact"
    if allowed_kinds is not None and kind not in allowed_kinds:
        return None
    confidence = max(0.0, min(1.0, float(rec.confidence)))
    if confidence < min_confidence:
        return None
    relevance = lexical_relevance(query, text)
    if relevance <= 0.0 and kind not in _QUERY_INDEPENDENT_KINDS:
        return None
    activity = rec.valid_at or rec.created_at or as_of
    importance = compute_importance(
        ImportanceInputs(
            recency_score=recency_score(last_accessed=_aware(activity), now=as_of),
            relevance_score=relevance,
        )
    )
    return MemoryHit(
        text=text[:2000],
        kind=kind[:32],
        confidence=confidence,
        score=max(0, int(importance * 100)),
        source="graph",
    )


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _durable_hit_from_item(
    item: dict[str, object],
    *,
    idx: int,
    limit: int,
    min_confidence: float,
    seen: set[str],
    allowed_kinds: set[str] | None = None,
) -> MemoryHit | None:
    if str(item.get("kind", "")).strip().lower() == "scratchpad":
        return None
    kind = str(item.get("kind", "fact")).strip().lower() or "fact"
    if allowed_kinds is not None and kind not in allowed_kinds:
        return None
    text = str(item.get("text", "")).strip()
    if not text or text.lower() in seen:
        return None
    # Stored confidence wins; else search-time `_score` (M2 importance) so Write
    # paths that omit confidence are not silently dropped by the Select gate.
    if "confidence" in item:
        confidence = max(0.0, min(1.0, coerce_float(item.get("confidence", 0.0))))
    else:
        confidence = max(0.0, min(1.0, coerce_float(item.get("_score", 0.0))))
    if confidence < min_confidence:
        return None
    score_f = _item_score(item)
    score = max(0, int(score_f * 100) if score_f else max(0, limit - idx))
    return MemoryHit(
        text=text[:2000],
        kind=kind[:32],
        confidence=confidence,
        score=score,
        source="medium",
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
    except Exception as exc:  # noqa: BLE001  # bump_access is telemetry; recall itself must succeed (060)
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
