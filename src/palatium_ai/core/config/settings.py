# src/palatium_ai/core/config/settings.py

"""Модуль settings содержит класс Settings, который наследуется от BaseSettings и содержит все настройки приложения."""

from collections.abc import Callable
from functools import lru_cache
from typing import ClassVar, cast

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from .app import AppConfig
from .attachments import AttachmentConfig
from .base import BaseConfig
from .contextualizer import ContextualizerConfig
from .database import DatabaseConfig, RedisConfig
from .embeddings import EmbeddingConfig
from .formatter import FormatterConfig
from .knowledge import KnowledgeConfig
from .llm import LLMConfig
from .logging import LoggingConfig
from .mcp import MCPConfig
from .memory import MemoryConfig
from .observability import ObservabilityConfig
from .retention import RetentionConfig
from .security import SecurityConfig
from .skills import SkillsConfig
from .web import WebConfig


def _load_database_config() -> DatabaseConfig:
    """BaseSettings читает POSTGRES_* без аргументов; stubs требуют user/password/db."""
    load = cast("Callable[[], DatabaseConfig]", DatabaseConfig)
    return load()


class Settings(BaseConfig):
    """Агрегатор всех конфигураций. Использует default_factory для инстанцирования суб-конфигов."""

    app: AppConfig = Field(default_factory=AppConfig)
    db: DatabaseConfig = Field(default_factory=_load_database_config)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    attachments: AttachmentConfig = Field(default_factory=AttachmentConfig)
    formatter: FormatterConfig = Field(default_factory=FormatterConfig)
    contextualizer: ContextualizerConfig = Field(default_factory=ContextualizerConfig)

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(frozen=True)

    @computed_field  # type: ignore[prop-decorator]  # pydantic plugin gap (017)
    @property
    def postgres_checkpointer_enabled(self) -> bool:
        """Durable AsyncPostgresSaver: explicit flag, else on for staging/production."""
        flag = self.memory.use_postgres_checkpointer
        if flag is not None:
            return flag
        return self.app.environment in ("staging", "production")

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


@lru_cache
def get_settings() -> Settings:
    """Провайдер настроек для FastAPI Depends."""
    return Settings()
