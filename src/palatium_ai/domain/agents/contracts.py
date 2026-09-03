# src/palatium_ai/domain/agents/contracts.py

"""Общие контракты межагентного взаимодействия."""

from typing import Literal

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """Контекст выполнения агента в рамках сессии."""

    model_config = {"frozen": True}

    thread_id: str
    user_id: str | None = None
    org_id: str | None = None


class TaskResult(BaseModel):
    """Унифицированный результат выполнения агента (legacy orchestration path).

    Миграция на ``AgentOutput`` (``domain/agents/messages.py``) + Harness —
    skill ``agent-refactoring``. Новый код не должен расширять этот контракт.
    """

    model_config = {"frozen": True}

    task_id: str
    agent_role: str
    status: Literal["success", "failure", "partial"]
    confidence: float = Field(ge=0.0, le=1.0)
    # Legacy HITL flag; prefer status="partial" + orchestrator escalation (030.7).
    requires_review: bool = Field(default=False)
    error: str | None = None
