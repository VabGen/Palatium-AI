# src/palatium_ai/infrastructure/embeddings/factory.py

"""Фабрика embedding-адаптеров с явной инъекцией настроек."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .litellm_adapter import LiteLLMEmbeddingAdapter

if TYPE_CHECKING:
    from palatium_ai.core.config.embeddings.base import EmbeddingProviderConfig
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.ports.embeddings import EmbeddingPort

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"cohere", "openai", "ollama", "qwen"})


class EmbeddingClientFactory:
    """Создаёт EmbeddingPort для указанного провайдера."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_client(self, provider_name: str | None = None) -> EmbeddingPort:
        """Возвращает адаптер для провайдера (или default из настроек)."""
        resolved = provider_name or self._settings.embeddings.default_provider
        if resolved not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"Unknown embedding provider: {resolved}")

        config: EmbeddingProviderConfig = getattr(self._settings.embeddings, resolved)
        return LiteLLMEmbeddingAdapter(config)


def create_embedding_client(settings: Settings, provider_name: str | None = None) -> EmbeddingPort:
    """Создаёт embedding-адаптер для указанного провайдера."""
    return EmbeddingClientFactory(settings).get_client(provider_name)
