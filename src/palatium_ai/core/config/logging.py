# src/palatium_ai/core/config/logging.py

"""Модуль logging содержит класс LoggingConfig, который наследуется от BaseConfig и содержит настройки логирования."""

from typing import Literal

from pydantic import Field

from .base import BaseConfig


class LoggingConfig(BaseConfig):
    """Настройки вывода логов."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", validation_alias="LOG_LEVEL")
    json_logs: bool = Field(default=False, validation_alias="LOG_JSON")
    file: str | None = Field(default=None, validation_alias="LOG_FILE")
    json_file: str | None = Field(default=None, validation_alias="LOG_JSON_FILE")
    filter_modules: str = Field(default="", validation_alias="LOG_FILTER_MODULES")
    # ``neo4j`` is suppressed because the driver logs every Bolt handshake, routing
    # decision and PING/PONG at DEBUG on the ``neo4j`` logger; with LOG_LEVEL=DEBUG the
    # turn's own spans drown in driver chatter (040). Driver failures still surface as
    # WARNING/ERROR and as exceptions from the adapter, so nothing is hidden.
    suppress_modules: str = Field(
        default="urllib3,asyncio,httpx,httpcore,openai,LiteLLM,litellm,neo4j",
        validation_alias="LOG_SUPPRESS_MODULES",
    )
