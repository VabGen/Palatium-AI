# src/palatium_ai/core/config/web.py

"""Web fallback / external search settings (070)."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from .base import BaseConfig


class WebConfig(BaseConfig):
    """Last-resort web search for ``platform.web_fallback``."""

    backend: Literal["stub", "http"] = Field(
        default="stub",
        validation_alias="WEB_FALLBACK_BACKEND",
    )
    provider: Literal["ddg", "brave"] = Field(
        default="ddg",
        validation_alias="WEB_FALLBACK_PROVIDER",
        description="ddg = DuckDuckGo Instant Answer (no key); brave = Brave Search API.",
    )
    api_key: SecretStr | None = Field(default=None, validation_alias="WEB_FALLBACK_API_KEY")
    timeout_seconds: float = Field(
        default=15.0,
        ge=2.0,
        le=60.0,
        validation_alias="WEB_FALLBACK_TIMEOUT_SECONDS",
    )
    retry_attempts: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias="WEB_FALLBACK_RETRY_ATTEMPTS",
    )
    retry_delay_seconds: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        validation_alias="WEB_FALLBACK_RETRY_DELAY_SECONDS",
    )
    circuit_failures_to_open: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="WEB_FALLBACK_CIRCUIT_FAILURES",
    )
    circuit_open_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        validation_alias="WEB_FALLBACK_CIRCUIT_OPEN_SECONDS",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_secret_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value
