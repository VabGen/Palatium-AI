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
    filter_modules: list[str] = Field(default_factory=list, validation_alias="LOG_FILTER_MODULES")
    suppress_modules: list[str] = Field(
        default_factory=lambda: ["urllib3", "asyncio", "httpx"], validation_alias="LOG_SUPPRESS_MODULES"
    )
