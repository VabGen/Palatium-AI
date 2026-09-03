# src/palatium_ai/infrastructure/embeddings/factory.py

"""Фабрика embedding-адаптеров с явной инъекцией настроек."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .litellm_adapter import LiteLLMEmbeddingAdapter

if TYPE_CHECKING:
    from palatium_ai.core.config.embeddings import EmbeddingSchema
    from palatium_ai.core.config.embeddings.base import EmbeddingProviderConfig
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.ports.embeddings import EmbeddingPort

logger = structlog.get_logger(__name__)

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

    def get_client_for_schema(self, schema: EmbeddingSchema) -> EmbeddingPort | None:
        """Adapter whose configured dim matches schema registry (060), or None."""
        embeddings = self._settings.embeddings
        expected = embeddings.expected_dim_for_schema(schema)
        name = embeddings.resolve_provider_name_for_schema(schema)
        if name is None:
            logger.warning(
                "embeddings.schema.provider_unmatched",
                schema=schema,
                expected_dim=expected,
                default_provider=embeddings.default_provider,
                hint=(
                    "Set MEMORY_EMBEDDING_PROVIDER / KNOWLEDGE_EMBEDDING_PROVIDER "
                    "to a provider whose *_EMBEDDING_DIMENSION matches the schema "
                    "(memory=4096, knowledge=1536). Vector path disabled until then."
                ),
            )
            return None
        logger.info(
            "embeddings.schema.provider_bound",
            schema=schema,
            provider=name,
            dimension=expected,
        )
        return self.get_client(name)


def create_embedding_client(settings: Settings, provider_name: str | None = None) -> EmbeddingPort:
    """Создаёт embedding-адаптер для указанного провайдера."""
    return EmbeddingClientFactory(settings).get_client(provider_name)


def create_embedding_client_for_schema(
    settings: Settings,
    schema: EmbeddingSchema,
) -> EmbeddingPort | None:
    """Schema-bound client, or None when no provider matches registry dims (060)."""
    return EmbeddingClientFactory(settings).get_client_for_schema(schema)
