# src/palatium_ai/core/types/embeddings.py

"""Embedding model ↔ schema ↔ dimension registry (060) — единственный источник."""

from __future__ import annotations

from typing import Literal

EmbeddingModel = Literal[
    "text-embedding-3-small",
    "qwen3-embedding-8b",
]

KnowledgeSchema = Literal["knowledge"]
MemorySchema = Literal["memory"]

KNOWLEDGE_EMBEDDING_MODEL: EmbeddingModel = "text-embedding-3-small"
# Corporate vLLM: root=Qwen/Qwen3-Embedding-8B, id=embedding-model — native 4096, no MRL on gateway.
MEMORY_EMBEDDING_MODEL: EmbeddingModel = "qwen3-embedding-8b"

KNOWLEDGE_EMBEDDING_DIM = 1536
MEMORY_EMBEDDING_DIM = 4096
# pgvector float32 HNSW/IVFFlat max dims. memory@4096 exceeds this → exact cosine (no float ANN).
# Future ANN: binary_quantize → bit(4096) HNSW, then optional cosine rerank on full vectors.
PGVECTOR_HNSW_MAX_VECTOR_DIM = 2000

_SCHEMA_MODEL: dict[str, EmbeddingModel] = {
    "knowledge": KNOWLEDGE_EMBEDDING_MODEL,
    "memory": MEMORY_EMBEDDING_MODEL,
}

_MODEL_DIM: dict[EmbeddingModel, int] = {
    KNOWLEDGE_EMBEDDING_MODEL: KNOWLEDGE_EMBEDDING_DIM,
    MEMORY_EMBEDDING_MODEL: MEMORY_EMBEDDING_DIM,
}


def embedding_model_for_schema(schema: str) -> EmbeddingModel:
    """Resolve canonical embedding model for a DB schema name."""
    try:
        return _SCHEMA_MODEL[schema]
    except KeyError as exc:
        msg = f"Unknown embedding schema: {schema}"
        raise KeyError(msg) from exc


def embedding_dim_for_model(model: EmbeddingModel) -> int:
    """Return vector dimension for a canonical embedding model."""
    return _MODEL_DIM[model]


def assert_vector_dim(*, schema: str, vector_len: int) -> None:
    """Fail before insert when vector length mismatches schema registry (060)."""
    model = embedding_model_for_schema(schema)
    expected = embedding_dim_for_model(model)
    if vector_len != expected:
        msg = f"Vector dim {vector_len} != {expected} for schema {schema} ({model})"
        raise ValueError(msg)
