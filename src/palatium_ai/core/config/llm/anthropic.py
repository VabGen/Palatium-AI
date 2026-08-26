# src/palatium_ai/core/config/llm/anthropic.py

"""Модуль AnthropicLLMConfig содержит класс AnthropicLLMConfig.

Класс AnthropicLLMConfig используется для конфигурирования LLM-провайдера Anthropic.
"""

from pydantic import Field, SecretStr

from .base import LLMProviderConfig


class AnthropicLLMConfig(LLMProviderConfig):
    """Настройки Anthropic."""

    provider_name: str = "anthropic"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    base_url: str = Field(
        default="https://api.anthropic.com",
        validation_alias="ANTHROPIC_BASE_URL",
    )
    default_model: str = Field(
        default="claude-3-5-sonnet-20240620",
        validation_alias="ANTHROPIC_DEFAULT_MODEL",
    )
    timeout: int = Field(default=60, validation_alias="ANTHROPIC_TIMEOUT")
    max_retries: int = Field(default=3, validation_alias="ANTHROPIC_MAX_RETRIES")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Anthropic."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Anthropic."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает дефолтную модель Anthropic."""
        return self.default_model
