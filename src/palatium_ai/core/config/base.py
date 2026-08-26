# src/palatium_ai/core/config/base.py

"""Базовый класс для всех конфигураций."""

import os

from typing import ClassVar
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Базовый класс с конфигурацией для чтения плоского .env файла."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", "env/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        env_nested_delimiter="__",
        env_prefix="",
        populate_by_name=True,
        frozen=True,
        validate_default=True,
    )


def validate_base_url(value: str, provider_name: str) -> str:
    """Проверяет корректность базового URL для провайдера."""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid {provider_name} URL: {value}")
    return value
