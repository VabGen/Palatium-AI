# src/palatium_ai/core/config/logging.py

"""Модуль logging содержит класс LoggingConfig, который наследуется от BaseConfig и содержит настройки логирования."""

from typing import Literal

from pydantic import Field

from .base import BaseConfig


class LoggingConfig(BaseConfig):
    """Настройки вывода логов."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    json_logs: bool = Field(default=False, validation_alias="LOG_JSON")
    file: str | None = Field(default=None, validation_alias="LOG_FILE")
    json_file: str | None = Field(default=None, validation_alias="LOG_JSON_FILE")
    filter_modules: str = Field(default="", validation_alias="LOG_FILTER_MODULES")
    suppress_modules: str = Field(
        default="urllib3,asyncio,httpx,httpcore,openai,LiteLLM,litellm",
        validation_alias="LOG_SUPPRESS_MODULES",
    )
