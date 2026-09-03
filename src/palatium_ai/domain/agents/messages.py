# src/palatium_ai/domain/agents/messages.py

"""Контракты AgentInput / AgentOutput (030) — единственный источник."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AgentInput(BaseModel):
    """Вход агента после JIT-сборки контекста Harness'ом."""

    model_config = {"frozen": True}

    task_id: UUID
    trace_id: str
    instruction: str
    context: dict[str, str] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    """Структурированный выход агента; output — подтип, объявленный агентом."""

    model_config = {"frozen": True}

    task_id: UUID
    status: Literal["success", "failure", "partial"]
    confidence: float = Field(ge=0.0, le=1.0)
    output: BaseModel
    error_message: str | None = None
