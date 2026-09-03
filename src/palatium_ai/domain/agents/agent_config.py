# src/palatium_ai/domain/agents/agent_config.py

"""AgentConfig — frozen pydantic (030)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import AgentRole, ModelTier


class AgentConfig(BaseModel):
    """Конфигурация агента."""

    model_config = {"frozen": True}

    name: str
    role: AgentRole
    model_tier: ModelTier
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    allowed_tools: tuple[str, ...] = Field(default_factory=tuple)
    timeout_seconds: int = Field(default=300, gt=0)
    max_retries: int = Field(default=3, ge=0)
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    llm_provider: Literal["openai", "anthropic", "ollama", "qwen"] | None = None
    llm_model: str | None = None

    embedding_provider: Literal["openai", "ollama", "qwen"] | None = None
    embedding_model: str | None = None
