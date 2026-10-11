"""Registry helpers for embedding observability labels (W4)."""

from __future__ import annotations

from palatium_ai.core.types.embeddings import (
    KNOWLEDGE_EMBEDDING_DIM,
    KNOWLEDGE_EMBEDDING_MODEL,
    MEMORY_EMBEDDING_DIM,
    MEMORY_EMBEDDING_MODEL,
    canonical_model_for_dim,
)


def test_canonical_model_for_memory_dim() -> None:
    assert canonical_model_for_dim(MEMORY_EMBEDDING_DIM) == MEMORY_EMBEDDING_MODEL


def test_canonical_model_for_knowledge_dim() -> None:
    assert canonical_model_for_dim(KNOWLEDGE_EMBEDDING_DIM) == KNOWLEDGE_EMBEDDING_MODEL


def test_canonical_model_unknown_dim() -> None:
    assert canonical_model_for_dim(999) is None
