# src/palatium_ai/application/services/memory_recall.py

"""Budgeted search over MemoryPort for the hot path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort

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
) -> MemoryRecallBundle:
    """Search thread (+ optional user/org) namespaces; drop low-confidence hits."""
    if memory_port is None or not query.strip():
        return MemoryRecallBundle(thread_id=thread_id, hits=(), max_items=limit, max_chars=max_chars)

    overfetch = max(limit * 3, 8)
    namespaces: list[tuple[str, ...]] = [thread_namespace(thread_id)]
    if user_id and user_id.strip():
        namespaces.append(user_namespace(user_id.strip()))
    if org_id and org_id.strip():
        namespaces.append(org_namespace(org_id.strip()))

    raw: list[dict[str, object]] = []
    for namespace in namespaces:
        raw.extend(
            await memory_port.search(
                namespace=namespace,
                query=query,
                limit=overfetch,
            )
        )

    hits: list[MemoryHit] = []
    seen_texts: set[str] = set()
    for idx, item in enumerate(sorted(raw, key=_item_score, reverse=True)):
        text = str(item.get("text", "")).strip()
        if not text or text in seen_texts:
            continue
        confidence = max(0.0, min(1.0, coerce_float(item.get("confidence", 0.0))))
        if confidence < min_confidence:
            continue
        seen_texts.add(text)
        hits.append(
            MemoryHit(
                text=text[:2000],
                kind=str(item.get("kind", "fact"))[:32],
                confidence=confidence,
                score=max(0, int(_item_score(item) * 100) if _item_score(item) else max(0, limit - idx)),
            )
        )
        if len(hits) >= limit:
            break
    return MemoryRecallBundle(
        thread_id=thread_id,
        hits=tuple(hits),
        max_items=limit,
        max_chars=max_chars,
    )


def _item_score(item: dict[str, object]) -> float:
    return coerce_float(item.get("_score", 0.0) or 0.0)
