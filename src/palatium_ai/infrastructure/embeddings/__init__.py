# src/palatium_ai/infrastructure/embeddings/__init__.py

"""Embedding-адаптеры и фабрика."""

from .factory import EmbeddingClientFactory, create_embedding_client
from .litellm_adapter import LiteLLMEmbeddingAdapter

__all__ = ["LiteLLMEmbeddingAdapter", "EmbeddingClientFactory", "create_embedding_client"]
