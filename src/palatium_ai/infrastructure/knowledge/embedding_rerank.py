# src/palatium_ai/infrastructure/knowledge/embedding_rerank.py

"""Optional semantic rerank over KnowledgePort hybrid hits (same pattern as memory)."""

from __future__ import annotations

import math

from typing import TYPE_CHECKING

from palatium_ai.domain.knowledge.types import KnowledgeSearchHit, KnowledgeSearchResult, SearchKnowledgeQuery

if TYPE_CHECKING:
    from palatium_ai.domain.knowledge.port import KnowledgePort
    from palatium_ai.domain.knowledge.types import IngestDocumentCommand, IngestDocumentResult
    from palatium_ai.domain.ports.embeddings import EmbeddingPort


class EmbeddingRerankKnowledgePort:
    """Decorator: over-fetch hybrid hits, rerank by query↔chunk cosine."""

    def __init__(
        self,
        inner: KnowledgePort,
        embeddings: EmbeddingPort,
        *,
        overfetch: int = 3,
    ) -> None:
        self._inner = inner
        self._embeddings = embeddings
        self._overfetch = max(2, overfetch)

    async def ingest_document(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        """Delegate ingest unchanged."""
        return await self._inner.ingest_document(command)

    async def search_knowledge(self, query: SearchKnowledgeQuery) -> KnowledgeSearchResult:
        """Hybrid candidate set → embedding cosine rerank (budgeted)."""
        safe_limit = max(1, min(query.limit, 32))
        overfetched = await self._inner.search_knowledge(
            query.model_copy(update={"limit": min(32, safe_limit * self._overfetch)})
        )
        hits = overfetched.hits
        if len(hits) <= 1:
            return KnowledgeSearchResult(hits=hits[:safe_limit], query=query.query)

        texts = [query.query.strip()] + [_hit_embed_text(hit) for hit in hits]
        try:
            vectors = await self._embeddings.embed(texts)
        except Exception:
            return KnowledgeSearchResult(hits=hits[:safe_limit], query=query.query)

        if len(vectors) != len(texts) or not vectors[0]:
            return KnowledgeSearchResult(hits=hits[:safe_limit], query=query.query)

        query_vec = vectors[0]
        scored: list[tuple[float, KnowledgeSearchHit]] = []
        for hit, vec in zip(hits, vectors[1:], strict=False):
            semantic = _cosine(query_vec, vec)
            hybrid = 0.65 * semantic + 0.35 * _normalize_lexical(hit.score)
            scored.append(
                (
                    hybrid,
                    hit.model_copy(update={"score": round(min(1.0, max(0.0, hybrid)), 4)}),
                )
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return KnowledgeSearchResult(
            hits=tuple(item for _, item in scored[:safe_limit]),
            query=query.query,
        )


def _hit_embed_text(hit: KnowledgeSearchHit) -> str:
    prefix = hit.contextual_prefix.strip()
    body = hit.text.strip()
    if prefix:
        return f"{prefix}\n\n{body}"
    return body


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
    if score <= 0:
        return 0.0
    return min(1.0, score / (score + 1.0))


__all__ = ["EmbeddingRerankKnowledgePort"]
