# src/palatium_ai/core/config/llm/qwen.py

"""Модуль QwenConfig содержит класс QwenConfig.

Класс QwenConfig используется для конфигурирования LLM-провайдера Qwen.
"""

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import LLMProviderConfig


class QwenLLMConfig(LLMProviderConfig):
    """Настройки Qwen (Alibaba Cloud)."""

    provider_name: str = "qwen"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="QWEN_API_KEY",
    )
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        validation_alias="QWEN_BASE_URL",
    )
    default_model: str = Field(
        default="qwen-turbo",
        validation_alias="QWEN_DEFAULT_MODEL",
    )
    timeout: int = Field(default=60, validation_alias="QWEN_TIMEOUT")
    max_retries: int = Field(default=3, validation_alias="QWEN_MAX_RETRIES")
    temperature: float = Field(default=0.1, validation_alias="QWEN_TEMPERATURE")
    max_tokens: int = Field(default=4096, validation_alias="QWEN_MAX_TOKENS")

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
        """Возвращает дефолтную модель Qwen."""
        return self.default_model
