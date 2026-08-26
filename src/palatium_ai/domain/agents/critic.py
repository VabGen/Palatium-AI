# src/palatium_ai/domain/agents/critic.py

"""Контракты агента Critic (quality gate)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.execution import ExecutionStrategy

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


class CriticOutput(BaseModel):
    """Оценка качества решения (LLM-as-a-Judge)."""

    model_config = {"frozen": True}

    accuracy_score: int = Field(ge=0, le=10)
    safety_score: int = Field(ge=0, le=10)
    requires_review: bool
    summary: str = Field(min_length=1)


class CriticTaskResult(TaskResult):
    """TaskResult с типизированным output для Critic."""

    output: CriticOutput | None = None
    requires_review: bool = Field(default=False)


ScoreGate = Literal["low_accuracy", "low_safety", "both_low", "ok"]
