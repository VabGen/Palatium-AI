# src/palatium_ai/core/config/security.py

"""
Модуль security содержит класс SecurityConfig.

Наследуется от BaseConfig и содержит настройки безопасности.
"""

from pydantic import Field, HttpUrl

from .base import BaseConfig


class SecurityConfig(BaseConfig):
    """Настройки безопасности."""

    jwt_algorithm: str = Field(default="RS256", validation_alias="JWT_ALGORITHM")
    jwks_url: HttpUrl = Field(validation_alias="JWKS_URL")
    api_rate_limit: int = Field(default=100, validation_alias="API_RATE_LIMIT")
