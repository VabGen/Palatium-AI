# src/palatium_ai/core/config/embeddings/ollama.py

"""Модуль OllamaEmbeddingConfig содержит класс OllamaEmbeddingConfig.

Класс OllamaEmbeddingConfig используется для конфигурирования embeddings-провайдера Ollama.
"""

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import EmbeddingProviderConfig


class OllamaEmbeddingConfig(EmbeddingProviderConfig):
    """Настройки эмбеддингов Ollama."""

    provider_name: str = "ollama"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OLLAMA_EMBEDDING_API_KEY",
    )

    base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_EMBEDDING_BASE_URL",
    )
    default_model: str = Field(
        default="nomic-embed-text",
        validation_alias="OLLAMA_EMBEDDING_MODEL",
    )
    dimension: int = Field(
        default=768,
        validation_alias="OLLAMA_EMBEDDING_DIMENSION",
    )
    timeout: int = Field(default=120, validation_alias="OLLAMA_EMBEDDING_TIMEOUT")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Проверяет, что URL Ollama корректен."""
        return validate_base_url(v, "Ollama")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Ollama."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Ollama."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает модель эмбеддингов Ollama по умолчанию."""
        return self.default_model

    def get_dimension(self) -> int:
        """Возвращает размерность вектора Ollama."""
        return self.dimension
