# src/palatium_ai/core/config/embeddings/qwen.py

"""Настройки embeddings-провайдера Qwen."""

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import EmbeddingProviderConfig


class QwenEmbeddingConfig(EmbeddingProviderConfig):
    """Настройки эмбеддингов Qwen (Alibaba Cloud)."""

    provider_name: str = "qwen"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="QWEN_EMBEDDING_API_KEY",
    )
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        validation_alias="QWEN_EMBEDDING_BASE_URL",
    )
    default_model: str = Field(
        default="text-embedding-v2",
        validation_alias="QWEN_EMBEDDING_MODEL",
    )
    dimension: int = Field(
        default=768,
        validation_alias="QWEN_EMBEDDING_DIMENSION",
    )
    timeout: int = Field(default=60, validation_alias="QWEN_EMBEDDING_TIMEOUT")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Проверяет, что URL Qwen корректен."""
        return validate_base_url(v, "Qwen")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Qwen."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Qwen."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает модель эмбеддингов Qwen по умолчанию."""
        return self.default_model

    def get_dimension(self) -> int:
        """Возвращает размерность вектора Qwen."""
        return self.dimension
