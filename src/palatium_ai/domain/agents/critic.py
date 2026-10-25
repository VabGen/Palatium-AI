# src/palatium_ai/domain/agents/critic.py

"""Контракты агента Critic (quality gate)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.execution import ExecutionStrategy
from palatium_ai.domain.policies.constitution import PrincipleId

from .context_packet import ContextPacket
from .contracts import TaskResult


class CriticInput(BaseModel):
    """Вход Critic агента."""

    model_config = {"frozen": True}

    task_id: str
    context_packet: ContextPacket
    classification_confidence: float = Field(ge=0.0, le=1.0)
    classification_reasoning: str = Field(min_length=1)
    worker_summary: str | None = None
    selected_strategy: ExecutionStrategy = "reason_only"
    continuation_kind: str | None = None
    user_input_chars: int = Field(default=0, ge=0)
    worker_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class CriticOutput(BaseModel):
    """Оценка качества решения (LLM-as-a-Judge).

    ``violations`` — article ids from :class:`~palatium_ai.domain.policies.constitution
    .Constitution`. The judge names them; deterministic checks may add theirs, and any
    violation forces ``requires_review`` (fail-closed, 020).
    """

    model_config = {"frozen": True}

    accuracy_score: int = Field(ge=0, le=10)
    safety_score: int = Field(ge=0, le=10)
    requires_review: bool
    summary: str = Field(min_length=1)
    violations: tuple[PrincipleId, ...] = ()


class CriticTaskResult(TaskResult):
    """TaskResult с типизированным output для Critic."""

    output: CriticOutput | None = None
    requires_review: bool = Field(default=False)


ScoreGate = Literal["low_accuracy", "low_safety", "both_low", "ok"]
