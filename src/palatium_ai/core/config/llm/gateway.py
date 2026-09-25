# src/palatium_ai/core/config/llm/gateway.py

"""Конфиг LiteLLM Gateway как OpenAI-совместимого провайдера."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import LLMProviderConfig


class GatewayLLMConfig(LLMProviderConfig):
    """Настройки LiteLLM Gateway."""

    provider_name: str = "gateway"

    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="PALATIUM_GATEWAY_KEY",
    )

    base_url: str = Field(
        default="http://litellm:4000",
        validation_alias="PALATIUM_GATEWAY_URL",
    )
    default_model: str = Field(
        default="tier-small",
        validation_alias="GATEWAY_DEFAULT_MODEL",
    )
    timeout: int = Field(default=120, validation_alias="GATEWAY_TIMEOUT")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Проверяет, что URL Gateway корректный."""
        return validate_base_url(v, "Gateway")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Gateway."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Gateway."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает дефолтную модель Gateway."""
        return self.default_model
