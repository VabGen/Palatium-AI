# src/palatium_ai/domain/agents/supervisor.py

"""Контракты агента Supervisor (routing/planning)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import TaskResult
from .intent import TaskKind

WorkerRoute = Literal["researcher", "formatter", "clarification"]


class SupervisorInput(BaseModel):
    """Вход Supervisor агента."""

    model_config = {"frozen": True}

    task_id: str
    user_text: str
    task_kind: TaskKind
    requires_mcp: bool
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    classification_confidence: float = Field(ge=0.0, le=1.0)


class SupervisorOutput(BaseModel):
    """План маршрутизации по типу задачи и capability needs."""

    model_config = {"frozen": True}

    route: WorkerRoute
    confidence: float = Field(ge=0.0, le=1.0)
    target_agent: str = Field(min_length=1)
    plan: str = Field(min_length=1)


class SupervisorTaskResult(TaskResult):
    """TaskResult с типизированным output для Supervisor."""

    output: SupervisorOutput | None = None
