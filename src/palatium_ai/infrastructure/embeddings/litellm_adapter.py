# src/palatium_ai/infrastructure/embeddings/litellm_adapter.py

"""LiteLLM-адаптер — единая реализация EmbeddingPort для всех провайдеров."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from litellm import aembedding

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
        logger.debug(
            "Embedding request",
            provider=self._provider,
            texts_count=len(texts),
            model=resolved_model,
        )
        try:
            response = await aembedding(**params)
            vectors = _extract_embeddings(response)
            if not vectors:
                raise RuntimeError(
                    "Embedding provider returned an empty vector list. Check model name, api_base, and response format."
                )
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
