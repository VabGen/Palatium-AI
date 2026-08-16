# src/palatium_ai/core/config.py

"""Настройки приложения с использованием Pydantic Settings."""

import os

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Настройки приложения, загружаемые из переменных окружения и .env файла.

    Все переменные должны быть явно описаны здесь с типами и валидацией.
    """

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Основные настройки приложения ---
    APP_NAME: str = Field(default="palatium-ai", alias="APP_NAME")
    APP_VERSION: str = Field(default="0.1.0", alias="APP_VERSION")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(default="development", alias="ENVIRONMENT")
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", alias="LOG_LEVEL")

    # --- Настройки логирования ---
    LOG_JSON: bool = Field(default=False, alias="LOG_JSON")
    LOG_FILE: str | None = Field(default=None, alias="LOG_FILE")
    LOG_JSON_FILE: str | None = Field(default=None, alias="LOG_JSON_FILE")
    LOG_SUPPRESS_MODULES: str = Field(
        default="urllib3,asyncio,httpx",
        alias="LOG_SUPPRESS_MODULES",
    )
    LOG_FILTER_MODULES: str = Field(default="", alias="LOG_FILTER_MODULES")

    # --- Базы данных и секреты (примеры) ---
    DATABASE_URL: PostgresDsn = Field(alias="DATABASE_URL")
    REDIS_URL: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    API_SECRET_KEY: SecretStr = Field(alias="API_SECRET_KEY")

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Проверяет, что значение LOG_LEVEL допустимо."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()


@lru_cache
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек (ленивая загрузка)."""
    return Settings()


settings = get_settings()
