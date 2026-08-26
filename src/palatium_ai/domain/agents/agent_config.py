# src/palatium_ai/domain/agents/agent_config.py

"""Модуль agent_config содержит класс AgentConfig.

Класс AgentConfig используется для конфигурирования агента.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Конфигурация агента."""

    model_config = {"frozen": True}

    name: str
    role: Literal[
        "text_ingestor",
        "intent_classifier",
        "supervisor",
        "reasoner",
        "planner",
        "context_weaver",
        "coder",
        "researcher",
        "analyst",
        "critic",
        "formatter",
        "memory_keeper",
    ]
    model_tier: Literal["nano", "small", "mid", "frontier", "deep_reasoning"]
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    allowed_tools: tuple[str, ...] = Field(default_factory=tuple)
    timeout_seconds: int = 300
    max_retries: int = 3
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    llm_provider: Literal["openai", "anthropic", "ollama", "qwen"] | None = None
    llm_model: str | None = None

    embedding_provider: Literal["openai", "ollama", "qwen"] | None = None
    embedding_model: str | None = None
