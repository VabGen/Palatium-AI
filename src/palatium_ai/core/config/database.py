# src/palatium_ai/core/config/database.py

"""Модуль database содержит настройки PostgreSQL и Redis."""

from pydantic import Field, SecretStr, computed_field, field_validator

from .base import BaseConfig


class DatabaseConfig(BaseConfig):
    """Настройки базы данных."""

    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    user: str = Field(validation_alias="POSTGRES_USER")
    password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    db: str = Field(validation_alias="POSTGRES_DB")
    db_schema: str = Field(default="public", validation_alias="POSTGRES_SCHEMA")
    pool_size: int = Field(default=10, validation_alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=20, validation_alias="DB_MAX_OVERFLOW")
    echo: bool = Field(default=False, validation_alias="DB_ECHO")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_dsn(self) -> str:
        """Возвращает асинхронный DSN для PostgreSQL."""
        secret = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{secret}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[prop-decorator]
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

    @field_validator("password", mode="before")
    @classmethod
    def _empty_password_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dsn(self) -> str:
        """Возвращает DSN для Redis."""
        if self.password is not None:
            secret = self.password.get_secret_value()
            if secret:
                return f"redis://:{secret}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"
