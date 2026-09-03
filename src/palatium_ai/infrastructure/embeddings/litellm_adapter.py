# src/palatium_ai/infrastructure/embeddings/litellm_adapter.py

"""LiteLLM-адаптер — единая реализация EmbeddingPort для всех провайдеров."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from litellm import aembedding

from palatium_ai.core.types.embeddings import MEMORY_EMBEDDING_DIM, assert_vector_dim
from palatium_ai.infrastructure.llm.litellm_model import resolve_litellm_model

if TYPE_CHECKING:
    from palatium_ai.core.config.embeddings.base import EmbeddingProviderConfig

logger = structlog.get_logger(__name__)


def _read_field(obj: object, key: str) -> object | None:
    """Read a field from dict-like or attribute-based LiteLLM responses."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_embeddings(response: object) -> list[list[float]]:
    """Extract embedding vectors from LiteLLM or OpenAI-compatible responses."""
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        if isinstance(dumped, dict):
            response = dumped

    data = _read_field(response, "data")
    if not isinstance(data, list):
        return []

    vectors: list[list[float]] = []
    for item in data:
        embedding = _read_field(item, "embedding")
        if isinstance(embedding, list):
            vectors.append([float(value) for value in embedding])
    return vectors


class LiteLLMEmbeddingAdapter:
    """Реализация EmbeddingPort через LiteLLM."""

    def __init__(self, config: EmbeddingProviderConfig) -> None:
        self._config = config
        self._api_key = config.get_api_key()
        self._base_url = config.get_base_url()
        self._default_model = config.get_default_model()
        self._provider = config.provider_name

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Преобразует тексты в векторы."""
        resolved_model = resolve_litellm_model(
            provider=self._provider,
            model=model or self._default_model,
            base_url=self._base_url,
        )
        params: dict[str, object] = {
            "model": resolved_model,
            "input": texts,
            "api_key": self._api_key,
            "api_base": self._base_url,
        }
        expected_dim = self._config.get_dimension()
        # Do not send `dimensions`: corporate vLLM rejects Matryoshka
        # ("does not support matryoshka representation"). Native width only.
        logger.debug(
            "Embedding request",
            provider=self._provider,
            texts_count=len(texts),
            model=resolved_model,
            expected_dim=expected_dim,
        )
        try:
            response = await aembedding(**params)
            vectors = _extract_embeddings(response)
            if not vectors:
                raise RuntimeError(
                    "Embedding provider returned an empty vector list. Check model name, api_base, and response format."
                )
            for vector in vectors:
                if len(vector) != expected_dim:
                    msg = f"Embedding dim {len(vector)} != configured {expected_dim}"
                    raise ValueError(msg)
                if expected_dim == MEMORY_EMBEDDING_DIM:
                    assert_vector_dim(schema="memory", vector_len=len(vector))
            logger.debug(
                "Embedding response received",
                provider=self._provider,
                vectors_count=len(vectors),
            )
            return vectors
        except Exception as exc:
            logger.error(
                "Embedding request failed",
                provider=self._provider,
                error=str(exc),
                exc_info=True,
            )
            raise
