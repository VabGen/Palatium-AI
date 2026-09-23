# src/palatium_ai/core/config/settings.py

"""Модуль settings содержит класс Settings, который наследуется от BaseSettings и содержит все настройки приложения."""

from functools import lru_cache
from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from .app import AppConfig
from .base import BaseConfig
from .database import DatabaseConfig, RedisConfig
from .embeddings import EmbeddingConfig
from .llm import LLMConfig
from .logging import LoggingConfig
from .mcp import MCPConfig
from .memory import MemoryConfig
from .observability import ObservabilityConfig
from .security import SecurityConfig
from .web import WebConfig


class Settings(BaseConfig):
    """Агрегатор всех конфигураций. Использует default_factory для инстанцирования суб-конфигов."""

    app: AppConfig = Field(default_factory=AppConfig)
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    web: WebConfig = Field(default_factory=WebConfig)

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(frozen=True)

    def mcp_jwt_signing_secret(self) -> str | None:
        """Secret for minting MCP JWTs: MCP_JWT_SECRET, else HS* JWT_SECRET."""
        dedicated = self.mcp.configured_jwt_secret()
        if dedicated is not None:
            return dedicated
        if self.security.jwt_secret is None:
            return None
        if not self.security.jwt_algorithm.startswith("HS"):
            return None
        text = self.security.jwt_secret.get_secret_value().strip()
        return text or None

    def resolve_mcp_bearer(self, server_name: str) -> str | None:
        """Bearer for Host→MCP: per-server static, else aud=mcp:<server> JWT, else shared static."""
        from palatium_ai.infrastructure.mcp.jwt_auth import resolve_mcp_bearer

        return resolve_mcp_bearer(
            self.mcp,
            server_name,
            signing_secret=self.mcp_jwt_signing_secret(),
        )


@lru_cache
def get_settings() -> Settings:
    """Провайдер настроек для FastAPI Depends."""
    return Settings()
