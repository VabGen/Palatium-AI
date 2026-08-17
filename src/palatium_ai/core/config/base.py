# src/palatium_ai/core/config/base.py

"""Базовый класс для всех конфигураций."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """
    Базовый класс с общей конфигурацией модели.

    $env:ENVIRONMENT="prod"; poetry run python -m palatium_ai.main
    """

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", "env/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )
