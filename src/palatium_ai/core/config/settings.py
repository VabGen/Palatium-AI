# src/palatium_ai/core/config/settings.py

"""Модуль settings содержит класс Settings, который наследуется от BaseSettings и содержит все настройки приложения."""

from functools import lru_cache

from .app import AppConfig
from .database import DatabaseConfig
from .logging import LoggingConfig
from .secrets import SecretsConfig


class Settings(
    AppConfig,
    LoggingConfig,
    DatabaseConfig,
    SecretsConfig,
):
    """Объединённый класс всех конфигураций приложения."""

    pass


@lru_cache
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек."""
    return Settings()


settings = get_settings()
