# src/palatium_ai/core/config/embeddings/openai.py

"""Модуль OpenAIEmbeddingConfig содержит класс OpenAIEmbeddingConfig.

Класс OpenAIEmbeddingConfig используется для конфигурирования embeddings-провайдера OpenAI.
"""

from pydantic import Field, SecretStr

from .base import EmbeddingProviderConfig


class OpenAIEmbeddingConfig(EmbeddingProviderConfig):
    """Настройки эмбеддингов OpenAI."""

    provider_name: str = "openai"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_EMBEDDING_API_KEY",
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_EMBEDDING_BASE_URL",
    )
    default_model: str = Field(
        default="text-embedding-ada-002",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )
    dimension: int = Field(
        default=1536,
        validation_alias="OPENAI_EMBEDDING_DIMENSION",
    )
    timeout: int = Field(default=60, validation_alias="OPENAI_EMBEDDING_TIMEOUT")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ OpenAI."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL OpenAI."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает модель эмбеддингов OpenAI по умолчанию."""
        return self.default_model

    def get_dimension(self) -> int:
        """Возвращает размерность вектора OpenAI."""
        return self.dimension
