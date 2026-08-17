# src/palatium_ai/core/config/settings.py

"""Модуль settings содержит класс Settings, который наследуется от BaseSettings и содержит все настройки приложения."""

from functools import lru_cache

from pydantic import Field

from .ai import LLMConfig, MCPConfig
from .app import AppConfig
from .base import BaseConfig
from .database import DatabaseConfig, RedisConfig
from .logging import LoggingConfig
from .observability import ObservabilityConfig
from .security import SecurityConfig


class Settings(BaseConfig):
    """Агрегатор всех конфигураций. Использует default_factory для инстанцирования суб-конфигов."""

    app: AppConfig = Field(default_factory=AppConfig)
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


@lru_cache
def get_settings() -> Settings:
    """Провайдер настроек для FastAPI Depends."""
    return Settings()
