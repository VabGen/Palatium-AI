# src/palatium_ai/core/config/database.py

"""Модуль database содержит класс DatabaseConfig, который наследуется от BaseConfig и содержит настройки базы данных."""

from pydantic import Field, model_validator

from .base import BaseConfig


class DatabaseConfig(BaseConfig):
    """Настройки базы данных."""

    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    user: str = Field(validation_alias="POSTGRES_USER")
    password: str = Field(validation_alias="POSTGRES_PASSWORD")
    db: str = Field(validation_alias="POSTGRES_DB")
    db_schema: str = Field(default="public", validation_alias="POSTGRES_SCHEMA")
    pool_size: int = Field(default=10, validation_alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=20, validation_alias="DB_MAX_OVERFLOW")
    echo: bool = Field(default=False, validation_alias="DB_ECHO")

    async_dsn: str = ""

    @model_validator(mode="after")
    def set_dsn(self) -> DatabaseConfig:
        """Устанавливает асинхронный DSN для PostgreSQL."""
        self.async_dsn = f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
        return self


class RedisConfig(BaseConfig):
    """Настройки Redis."""

    host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    port: int = Field(default=6379, validation_alias="REDIS_PORT")
    db: int = Field(default=0, validation_alias="REDIS_DB")
    password: str | None = Field(default=None, validation_alias="REDIS_PASSWORD")

    dsn: str = ""

    @model_validator(mode="after")
    def set_dsn(self) -> RedisConfig:
        """Устанавливает DSN для Redis."""
        if self.password:
            self.dsn = f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        else:
            self.dsn = f"redis://{self.host}:{self.port}/{self.db}"
        return self
