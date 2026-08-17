# src/palatium_ai/core/config/observability.py

"""
Модуль observability содержит класс ObservabilityConfig.

Наследуется от BaseConfig и содержит настройки мониторинга и телеметрии.
"""

from pydantic import Field, SecretStr

from .base import BaseConfig


class ObservabilityConfig(BaseConfig):
    """Настройки мониторинга и телеметрии."""

    langchain_tracing_v2: bool = Field(default=True, validation_alias="LANGCHAIN_TRACING_V2")
    langchain_api_key: SecretStr | None = Field(default=None, validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field(default="palatium-ai-prod", validation_alias="LANGCHAIN_PROJECT")
    otel_endpoint: str | None = Field(default=None, validation_alias="OTEL_ENDPOINT")
