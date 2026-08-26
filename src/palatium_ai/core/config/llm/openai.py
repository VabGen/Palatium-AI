# src/palatium_ai/core/config/llm/openai.py

"""Модуль OpenAILLMConfig содержит класс OpenAILLMConfig.

Класс OpenAILLMConfig используется для конфигурирования LLM-провайдера OpenAI.
"""

from pydantic import Field, SecretStr

from .base import LLMProviderConfig


class OpenAILLMConfig(LLMProviderConfig):
    """Настройки OpenAI."""

    provider_name: str = "openai"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    default_model: str = Field(
        default="gpt-4o",
        validation_alias="OPENAI_DEFAULT_MODEL",
    )
    timeout: int = Field(default=60, validation_alias="OPENAI_TIMEOUT")
    max_retries: int = Field(default=3, validation_alias="OPENAI_MAX_RETRIES")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ OpenAI."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL OpenAI."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает дефолтную модель OpenAI."""
        return self.default_model
