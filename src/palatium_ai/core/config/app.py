# src/palatium_ai/core/config/app.py

"""Модуль app содержит класс AppConfig, который наследуется от BaseConfig и содержит настройки приложения."""

from typing import Literal

from pydantic import Field

from .base import BaseConfig


class AppConfig(BaseConfig):
    """Общие настройки приложения."""

    APP_NAME: str = Field(default="palatium-ai")
    APP_VERSION: str = Field(default="0.1.0")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(default="development")
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
