# src/palatium_ai/infrastructure/memory/embedding_rerank.py

"""Optional semantic rerank over MemoryPort search hits (FTS/token first)."""

from __future__ import annotations

import math

from typing import TYPE_CHECKING

from palatium_ai.core.types.coerce import coerce_float

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.ports.embeddings import EmbeddingPort


class EmbeddingRerankMemoryPort:
    """Decorator: over-fetch lexical hits, rerank by cosine similarity."""

    def __init__(
        self,
        inner: MemoryPort,
        embeddings: EmbeddingPort,
        *,
        overfetch: int = 3,
    ) -> None:
        self._inner = inner
        self._embeddings = embeddings
        self._overfetch = max(2, overfetch)

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Delegate upsert to inner port."""
        await self._inner.put(namespace=namespace, key=key, value=value)

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Delegate get to inner port."""
        return await self._inner.get(namespace=namespace, key=key)

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Lexical candidate set → embedding cosine rerank (budgeted)."""
        safe_limit = max(1, min(limit, 32))
        candidates = await self._inner.search(
            namespace=namespace,
            query=query,
            limit=min(32, safe_limit * self._overfetch),
        )
        if len(candidates) <= 1:
            return candidates[:safe_limit]

        texts = [query.strip()] + [str(item.get("text", "")).strip() for item in candidates]
        try:
            vectors = await self._embeddings.embed(texts)
        except Exception:
            return candidates[:safe_limit]

        if len(vectors) != len(texts) or not vectors[0]:
            return candidates[:safe_limit]

        query_vec = vectors[0]
        scored: list[tuple[float, dict[str, object]]] = []
        for item, vec in zip(candidates, vectors[1:], strict=False):
            lexical = coerce_float(item.get("_score", 0.0) or 0.0)
            semantic = _cosine(query_vec, vec)
            # Hybrid: prefer semantic when available, keep lexical as tie-break.
            hybrid = 0.65 * semantic + 0.35 * _normalize_lexical(lexical)
            enriched = dict(item)
            enriched["_score"] = round(hybrid, 4)
            enriched["_semantic"] = round(semantic, 4)
            scored.append((hybrid, enriched))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:safe_limit]]

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Delegate delete to inner port."""
        return await self._inner.forget(namespace=namespace, key=key)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    n = min(len(left), len(right))
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for idx in range(n):
        a = left[idx]
        b = right[idx]
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _normalize_lexical(score: float) -> float:
    """Map unbounded lexical/FTS scores into ~[0,1] for blending."""
    if score <= 0:
        return 0.0
    return min(1.0, score / (score + 1.0))
