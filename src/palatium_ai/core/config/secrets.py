# src/palatium_ai/core/config/secrets.py

"""Модуль secrets содержит класс SecretsConfig, который наследуется от BaseConfig и содержит настройки секретов."""

from pydantic import Field, SecretStr

from .base import BaseConfig


class SecretsConfig(BaseConfig):
    """Секретные настройки (не попадают в логи)."""

    API_SECRET_KEY: SecretStr = Field(alias="API_SECRET_KEY")
