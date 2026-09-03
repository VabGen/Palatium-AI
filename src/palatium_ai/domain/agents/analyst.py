# src/palatium_ai/domain/agents/analyst.py

"""Контракты Analyst — структурированный анализ по контексту."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .context_packet import ContextPacket
from .contracts import TaskResult


class AnalystInput(BaseModel):
    """Вход Analyst агента."""

    model_config = {"frozen": True}

    task_id: str
    context_packet: ContextPacket
    revision_feedback: str | None = Field(default=None, max_length=4_000)


class AnalystOutput(BaseModel):
    """Аналитический черновик (тренды/сводки без code-exec)."""

    model_config = {"frozen": True}

    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    findings: tuple[str, ...] = Field(default_factory=tuple)


class AnalystTaskResult(TaskResult):
    """TaskResult с типизированным output для Analyst."""

    output: AnalystOutput | None = None
