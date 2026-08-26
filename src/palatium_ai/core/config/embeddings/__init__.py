# src/palatium_ai/core/config/embeddings/__init__.py

"""Модуль для настроек embeddings."""

from typing import cast

from pydantic import Field, model_validator

from palatium_ai.core.config.base import BaseConfig

from .base import EmbeddingProviderConfig
from .cohere import CohereEmbeddingConfig
from .ollama import OllamaEmbeddingConfig
from .openai import OpenAIEmbeddingConfig
from .qwen import QwenEmbeddingConfig


class EmbeddingConfig(BaseConfig):
    """Агрегатор конфигураций провайдеров эмбеддингов."""

    openai: OpenAIEmbeddingConfig = Field(default_factory=OpenAIEmbeddingConfig)
    ollama: OllamaEmbeddingConfig = Field(default_factory=OllamaEmbeddingConfig)
    qwen: QwenEmbeddingConfig = Field(default_factory=QwenEmbeddingConfig)
    cohere: CohereEmbeddingConfig = Field(default_factory=CohereEmbeddingConfig)

    default_provider: str = Field(
        default="openai",
        validation_alias="EMBEDDING_DEFAULT_PROVIDER",
    )

    @model_validator(mode="after")
    def validate_default_provider(self) -> EmbeddingConfig:
        """Проверяет, что выбранный провайдер существует и корректно сконфигурирован."""
        if self.default_provider not in {"openai", "ollama", "qwen", "cohere"}:
            raise ValueError(f"Unknown embedding provider: {self.default_provider}")
        provider = getattr(self, self.default_provider)
        if (
            isinstance(
                provider,
                (OpenAIEmbeddingConfig, QwenEmbeddingConfig, CohereEmbeddingConfig),
            )
            and provider.api_key is None
        ):
            raise ValueError(f"API key for {self.default_provider} embedding is not set")
        return self

    def get_active_provider(self) -> EmbeddingProviderConfig:
        """Возвращает активный провайдер эмбеддингов."""
        return cast("EmbeddingProviderConfig", getattr(self, self.default_provider))


__all__ = [
    "EmbeddingConfig",
    "OpenAIEmbeddingConfig",
    "OllamaEmbeddingConfig",
    "QwenEmbeddingConfig",
    "CohereEmbeddingConfig",
    "EmbeddingProviderConfig",
]
