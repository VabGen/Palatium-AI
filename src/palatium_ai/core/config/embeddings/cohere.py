# src/palatium_ai/core/config/embeddings/cohere.py

"""Настройки embeddings-провайдера Cohere."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import EmbeddingProviderConfig


class CohereEmbeddingConfig(EmbeddingProviderConfig):
    """Настройки эмбеддингов Cohere."""

    provider_name: str = "cohere"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="COHERE_EMBEDDING_API_KEY",
    )
    base_url: str = Field(
        default="https://api.cohere.com/v1",
        validation_alias="COHERE_EMBEDDING_BASE_URL",
    )
    default_model: str = Field(
        default="embed-multilingual-v3.0",
        validation_alias="COHERE_EMBEDDING_MODEL",
    )
    dimension: int = Field(
        default=1024,
        validation_alias="COHERE_EMBEDDING_DIMENSION",
    )
    timeout: int = Field(default=60, validation_alias="COHERE_EMBEDDING_TIMEOUT")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Проверяет корректность базового URL Cohere."""
        return validate_base_url(value, "Cohere")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Cohere."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Cohere."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает модель эмбеддингов Cohere по умолчанию."""
        return self.default_model

    def get_dimension(self) -> int:
        """Возвращает размерность вектора Cohere."""
        return self.dimension
