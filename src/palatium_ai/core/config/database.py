# src/palatium_ai/core/config/database.py

"""Модуль database содержит класс DatabaseConfig, который наследуется от BaseConfig и содержит настройки базы данных."""

from pydantic import Field, PostgresDsn

from .base import BaseConfig


class DatabaseConfig(BaseConfig):
    """Настройки БД и кэша."""

    DATABASE_URL: PostgresDsn = Field(alias="DATABASE_URL")
    REDIS_URL: str = Field(default="redis://localhost:6379")
