# src/palatium_ai/core/config/logging.py

"""Модуль logging содержит класс LoggingConfig, который наследуется от BaseConfig и содержит настройки логирования."""

from pydantic import Field

from .base import BaseConfig


class LoggingConfig(BaseConfig):
    """Настройки вывода логов."""

    LOG_JSON: bool = Field(default=False)
    LOG_FILE: str | None = Field(default=None)
    LOG_JSON_FILE: str | None = Field(default=None)
    LOG_SUPPRESS_MODULES: str = Field(
        default="urllib3,asyncio,httpx",
        description="Модули, уровень которых ставится WARNING (через запятую)",
    )
    LOG_FILTER_MODULES: str = Field(
        default="",
        description="Модули, логи которых полностью игнорируются (через запятую)",
    )
