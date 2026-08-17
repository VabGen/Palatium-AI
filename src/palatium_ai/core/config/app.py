# src/palatium_ai/core/config/app.py

"""Модуль app содержит класс AppConfig, который наследуется от BaseConfig и содержит настройки приложения."""

from typing import Literal

from pydantic import Field

from .base import BaseConfig


class AppConfig(BaseConfig):
    """Общие настройки приложения."""

    name: str = Field(default="palatium-ai", validation_alias="APP_NAME")
    version: str = Field(default="0.1.0", validation_alias="APP_VERSION")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", validation_alias="ENVIRONMENT"
    )
