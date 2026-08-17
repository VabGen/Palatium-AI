# src/palatium_ai/core/config/database.py

"""Модуль database содержит класс DatabaseConfig, который наследуется от BaseConfig и содержит настройки базы данных."""

from pydantic import Field, computed_field

from .base import BaseConfig


class DatabaseConfig(BaseConfig):
    """Настройки PostgreSQL."""

    POSTGRES_HOST: str = Field(default="localhost", alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    POSTGRES_USER: str = Field(alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(alias="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field(alias="POSTGRES_DB")
    POSTGRES_SCHEMA: str = Field(default="public", alias="POSTGRES_SCHEMA")

    DB_POOL_SIZE: int = Field(default=10, alias="DB_POOL_SIZE")
    DB_MAX_OVERFLOW: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    DB_ECHO: bool = Field(default=False, alias="DB_ECHO")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        """Формирует URL для подключения к БД."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class RedisConfig(BaseConfig):
    """Настройки Redis."""

    REDIS_HOST: str = Field(default="localhost", alias="REDIS_HOST")
    REDIS_PORT: int = Field(default=6379, alias="REDIS_PORT")
    REDIS_DB: int = Field(default=0, alias="REDIS_DB")
    REDIS_PASSWORD: str | None = Field(default=None, alias="REDIS_PASSWORD")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:  # noqa: N802
        """Формирует URL для подключения к Redis."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
