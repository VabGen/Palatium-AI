# src/palatium_ai/infrastructure/embeddings/__init__.py

"""Embedding-адаптеры и фабрика."""

from .factory import EmbeddingClientFactory, create_embedding_client, create_embedding_client_for_schema
from .litellm_adapter import LiteLLMEmbeddingAdapter

__all__ = [
    "LiteLLMEmbeddingAdapter",
    "EmbeddingClientFactory",
    "create_embedding_client",
    "create_embedding_client_for_schema",
]
