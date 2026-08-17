# src/palatium_ai/core/config/ai.py

"""Модуль ai содержит класс AiConfig, который наследуется от BaseConfig и содержит настройки AI."""

from pydantic import Field, SecretStr

from .base import BaseConfig


class LLMConfig(BaseConfig):
    """Настройки LLM."""

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    default_model: str = Field(default="gpt-4o", validation_alias="LLM_DEFAULT_MODEL")
    max_tokens: int = Field(default=4096, validation_alias="LLM_MAX_TOKENS")
    temperature: float = Field(default=0.1, validation_alias="LLM_TEMPERATURE")


class MCPConfig(BaseConfig):
    """Настройки MCP."""

    enabled: bool = Field(default=True, validation_alias="MCP_ENABLED")
    endpoints: list[str] = Field(default_factory=list, validation_alias="MCP_ENDPOINTS")
    timeout_seconds: int = Field(default=30, validation_alias="MCP_TIMEOUT_SECONDS")
