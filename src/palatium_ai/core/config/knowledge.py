# src/palatium_ai/core/config/knowledge.py

"""Knowledge-index retrieval settings (hybrid fusion)."""

from __future__ import annotations

from pydantic import Field

from palatium_ai.core.types.knowledge import DEFAULT_RRF_K, KnowledgeHybridFusion

from .base import BaseConfig


class KnowledgeConfig(BaseConfig):
    """How FTS + dense hits are fused (and optionally reranked) for ``search_knowledge``."""

    hybrid_fusion: KnowledgeHybridFusion = Field(
        default="weighted",
        validation_alias="KNOWLEDGE_HYBRID_FUSION",
    )
    #: Reciprocal Rank Fusion constant (Cormack et al.); only used when fusion=rrf.
    rrf_k: int = Field(default=DEFAULT_RRF_K, ge=1, le=200, validation_alias="KNOWLEDGE_RRF_K")
    #: After hybrid merge, over-fetch and rerank by knowledge-schema embedding cosine.
    #: Requires a working knowledge embedding client; otherwise the flag is ignored.
    embedding_rerank: bool = Field(
        default=False,
        validation_alias="KNOWLEDGE_EMBEDDING_RERANK",
    )
    embedding_rerank_overfetch: int = Field(
        default=3,
        ge=2,
        le=8,
        validation_alias="KNOWLEDGE_EMBEDDING_RERANK_OVERFETCH",
    )


__all__ = ["KnowledgeConfig", "KnowledgeHybridFusion"]
