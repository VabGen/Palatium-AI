# src/palatium_ai/core/config/database.py

"""Модуль database содержит настройки PostgreSQL и Redis."""

from typing import Self

from pydantic import Field, SecretStr, ValidationInfo, computed_field, field_validator, model_validator

from palatium_ai.core.security.identifiers import assert_safe_sql_identifier

from .base import BaseConfig


class DatabaseConfig(BaseConfig):
    """Настройки базы данных."""

    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    user: str = Field(validation_alias="POSTGRES_USER")
    password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    db: str = Field(validation_alias="POSTGRES_DB")
    db_schema: str = Field(default="public", validation_alias="POSTGRES_SCHEMA")
    pool_size: int = Field(default=10, ge=1, validation_alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=20, ge=0, validation_alias="DB_MAX_OVERFLOW")
    pool_pre_ping: bool = Field(default=True, validation_alias="DB_POOL_PRE_PING")
    pool_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="DB_POOL_TIMEOUT_SECONDS")
    connect_timeout_seconds: float = Field(default=15.0, gt=0, validation_alias="DB_CONNECT_TIMEOUT_SECONDS")
    startup_timeout_seconds: float = Field(default=60.0, gt=0, validation_alias="DB_STARTUP_TIMEOUT_SECONDS")
    echo: bool = Field(default=False, validation_alias="DB_ECHO")
    # Connection-acquisition retry (035): Postgres answers 57P03 while it recovers from a
    # restart, so a brief bounded retry keeps a restart from surfacing as an ASGI 500.
    # 1 attempt = fail fast (no retry at all).
    retry_attempts: int = Field(default=4, ge=1, validation_alias="DB_RETRY_ATTEMPTS")
    retry_initial_delay_seconds: float = Field(
        default=0.25,
        gt=0,
        validation_alias="DB_RETRY_INITIAL_DELAY_SECONDS",
    )
    retry_max_delay_seconds: float = Field(default=2.0, gt=0, validation_alias="DB_RETRY_MAX_DELAY_SECONDS")

    @model_validator(mode="after")
    def _retry_window_is_coherent(self) -> Self:
        """Верхняя граница backoff'а не может быть меньше первой паузы (010: падать на загрузке)."""
        if self.retry_max_delay_seconds < self.retry_initial_delay_seconds:
            raise ValueError("DB_RETRY_MAX_DELAY_SECONDS must be >= DB_RETRY_INITIAL_DELAY_SECONDS")
        return self

    @field_validator("db", "db_schema")
    @classmethod
    def _identifiers_are_ddl_safe(cls, value: str, info: ValidationInfo) -> str:
        """DDL names are interpolated (no bind params possible) — validate at load (020)."""
        return assert_safe_sql_identifier(value, kind=str(info.field_name))

    @computed_field  # type: ignore[prop-decorator]  # плагин pydantic не моделирует computed_field (017)
    @property
    def async_dsn(self) -> str:
        """Возвращает асинхронный DSN для PostgreSQL."""
        secret = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{secret}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[prop-decorator]  # плагин pydantic не моделирует computed_field (017)
    @property
    def psycopg_dsn(self) -> str:
        """DSN for psycopg / LangGraph AsyncPostgresSaver (not SQLAlchemy)."""
        secret = self.password.get_secret_value()
        return f"postgresql://{self.user}:{secret}@{self.host}:{self.port}/{self.db}"


class RedisConfig(BaseConfig):
    """Настройки Redis."""

    host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    port: int = Field(default=6379, validation_alias="REDIS_PORT")
    db: int = Field(default=0, validation_alias="REDIS_DB")
    password: SecretStr | None = Field(default=None, validation_alias="REDIS_PASSWORD")
    max_connections: int = Field(default=20, ge=1, validation_alias="REDIS_MAX_CONNECTIONS")
    socket_timeout_seconds: float = Field(default=5.0, gt=0, validation_alias="REDIS_SOCKET_TIMEOUT_SECONDS")
    socket_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
    )
    health_check_interval_seconds: int = Field(default=30, ge=0, validation_alias="REDIS_HEALTH_CHECK_INTERVAL_SECONDS")
    socket_keepalive: bool = Field(default=True, validation_alias="REDIS_SOCKET_KEEPALIVE")

    @field_validator("password", mode="before")
    @classmethod
    def _empty_password_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @computed_field  # type: ignore[prop-decorator]  # плагин pydantic не моделирует computed_field (017)
    @property
    def dsn(self) -> str:
        """Возвращает DSN для Redis."""
        if self.password is not None:
            secret = self.password.get_secret_value()
            if secret:
                return f"redis://:{secret}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"
