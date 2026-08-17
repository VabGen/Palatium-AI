# src/palatium_ai/core/config/base.py

"""Базовый класс для всех конфигураций."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Базовый класс с конфигурацией для чтения плоского .env файла."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", "env/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        env_nested_delimiter="__",
        env_prefix="",
        # env_skip_empty=True,
        # env_skip_none=True,
        # env_skip_default=True,
    )
