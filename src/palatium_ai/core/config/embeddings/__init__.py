# src/palatium_ai/core/config/embeddings/__init__.py

"""Модуль для настроек embeddings."""

from __future__ import annotations

from typing import Literal, cast

from pydantic import Field, field_validator, model_validator

from palatium_ai.core.config.base import BaseConfig
from palatium_ai.core.types.embeddings import embedding_dim_for_model, embedding_model_for_schema

from .base import EmbeddingProviderConfig
from .cohere import CohereEmbeddingConfig
from .ollama import OllamaEmbeddingConfig
from .openai import OpenAIEmbeddingConfig
from .qwen import QwenEmbeddingConfig

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "ollama", "qwen", "cohere"})
EmbeddingSchema = Literal["memory", "knowledge"]


def _empty_str_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


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
    # Per-schema override (060): memory=4096 native, knowledge=1536 — not the same as default_provider.
    memory_provider: str | None = Field(
        default=None,
        validation_alias="MEMORY_EMBEDDING_PROVIDER",
    )
    knowledge_provider: str | None = Field(
        default=None,
        validation_alias="KNOWLEDGE_EMBEDDING_PROVIDER",
    )

    @field_validator("memory_provider", "knowledge_provider", mode="before")
    @classmethod
    def blank_schema_provider_to_none(cls, value: object) -> object:
        """Treat empty env values as unset."""
        return _empty_str_to_none(value)

    @model_validator(mode="after")
    def validate_default_provider(self) -> EmbeddingConfig:
        """Проверяет, что выбранный провайдер существует и корректно сконфигурирован."""
        if self.default_provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"Unknown embedding provider: {self.default_provider}")
        self._assert_provider_ready(self.default_provider, label="default")
        for name, label in (
            (self.memory_provider, "MEMORY_EMBEDDING_PROVIDER"),
            (self.knowledge_provider, "KNOWLEDGE_EMBEDDING_PROVIDER"),
        ):
            if name is None:
                continue
            if name not in _SUPPORTED_PROVIDERS:
                raise ValueError(f"Unknown embedding provider in {label}: {name}")
            self._assert_provider_ready(name, label=label)
        return self

    def _assert_provider_ready(self, name: str, *, label: str) -> None:
        provider = getattr(self, name)
        if (
            isinstance(
                provider,
                (OpenAIEmbeddingConfig, QwenEmbeddingConfig, CohereEmbeddingConfig),
            )
            and provider.api_key is None
        ):
            raise ValueError(f"API key for {label} embedding provider '{name}' is not set")

    def get_active_provider(self) -> EmbeddingProviderConfig:
        """Возвращает активный провайдер эмбеддингов."""
        return cast("EmbeddingProviderConfig", getattr(self, self.default_provider))

    def expected_dim_for_schema(self, schema: EmbeddingSchema) -> int:
        """Canonical vector size for a DB schema (060 registry)."""
        return embedding_dim_for_model(embedding_model_for_schema(schema))

    def resolve_provider_name_for_schema(self, schema: EmbeddingSchema) -> str | None:
        """Pick a configured provider whose dimension matches the schema registry.

        Order: schema override → default_provider → other providers with matching dim.
        Returns None when no configured provider matches (caller uses FTS-only / no vectors).
        """
        expected = self.expected_dim_for_schema(schema)
        explicit = self.memory_provider if schema == "memory" else self.knowledge_provider
        ordered: list[str] = []
        for name in (explicit, self.default_provider, *_SUPPORTED_PROVIDERS):
            if name is None or name in ordered:
                continue
            ordered.append(name)

        for name in ordered:
            provider = cast("EmbeddingProviderConfig", getattr(self, name))
            if provider.get_dimension() != expected:
                continue
            if (
                isinstance(
                    provider,
                    (OpenAIEmbeddingConfig, QwenEmbeddingConfig, CohereEmbeddingConfig),
                )
                and provider.api_key is None
            ):
                continue
            return name
        return None


__all__ = [
    "EmbeddingConfig",
    "EmbeddingSchema",
    "OpenAIEmbeddingConfig",
    "OllamaEmbeddingConfig",
    "QwenEmbeddingConfig",
    "CohereEmbeddingConfig",
    "EmbeddingProviderConfig",
]
