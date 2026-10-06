# src/palatium_ai/core/config/base.py

"""Базовый класс для всех конфигураций."""

import os

from typing import ClassVar
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = "env/.env"


def resolve_env_file() -> str:
    """Path to the settings env file.

    Matches the Makefile normalisation: a *defined but empty* ``ENV_FILE=`` must
    not disable the file (shell env outranks ``--env-file`` / pydantic sources,
    and blank path loads nothing — then empty ``POSTGRES_HOST``/``PORT`` from the
    process surface as a cryptic ValidationError on alembic/API boot).
    """
    raw = os.getenv("ENV_FILE")
    if raw is None:
        return _DEFAULT_ENV_FILE
    stripped = raw.strip()
    return stripped or _DEFAULT_ENV_FILE


class BaseConfig(BaseSettings):
    """Базовый класс с конфигурацией для чтения плоского .env файла."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding="utf-8",
        # Empty process env (``POSTGRES_HOST=``) must not beat values from the env file.
        env_ignore_empty=True,
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
