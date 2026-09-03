# palatium_ai/core/types/__init__.py

"""Shared type helpers and registries."""

from .coerce import coerce_float
from .embeddings import (
    KNOWLEDGE_EMBEDDING_DIM,
    KNOWLEDGE_EMBEDDING_MODEL,
    MEMORY_EMBEDDING_DIM,
    MEMORY_EMBEDDING_MODEL,
    EmbeddingModel,
    assert_vector_dim,
    embedding_dim_for_model,
    embedding_model_for_schema,
)
from .graph_nodes import (
    LEGACY_GRAPH_NODE_IDS,
    NODE_ANALYST,
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_INTENT_CLASSIFIER,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
    NODE_SUPERVISOR,
)
from .model_registry import abstract_tier_for, context_limit_tokens
from .uuid import UUIDv7

__all__ = [
    "UUIDv7",
    "coerce_float",
    "EmbeddingModel",
    "KNOWLEDGE_EMBEDDING_DIM",
    "KNOWLEDGE_EMBEDDING_MODEL",
    "MEMORY_EMBEDDING_DIM",
    "MEMORY_EMBEDDING_MODEL",
    "assert_vector_dim",
    "embedding_dim_for_model",
    "embedding_model_for_schema",
    "abstract_tier_for",
    "context_limit_tokens",
    "LEGACY_GRAPH_NODE_IDS",
    "NODE_CONTEXT_ENRICHER_CONTINUATION",
    "NODE_CONTEXT_ENRICHER_WEAVING",
    "NODE_ANALYST",
    "NODE_CODER",
    "NODE_CRITIC",
    "NODE_FORMATTER",
    "NODE_INTENT_CLASSIFIER",
    "NODE_QUALITY_REVISION",
    "NODE_RESEARCHER",
    "NODE_SUPERVISOR",
]
