# src/palatium_ai/domain/agents/coder.py

"""Контракты Coder — draft/plan кода без произвольного exec (020 sandbox/HITL)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .context_packet import ContextPacket
from .contracts import TaskResult


class CoderInput(BaseModel):
    """Вход Coder агента."""

    model_config = {"frozen": True}

    task_id: str
    context_packet: ContextPacket
    revision_feedback: str | None = Field(default=None, max_length=4_000)


class CoderOutput(BaseModel):
    """Черновик кода / план реализации (не исполненный sandbox)."""

    model_config = {"frozen": True}

    summary: str = Field(min_length=1, description="Human-readable plan or code draft.")
    confidence: float = Field(ge=0.0, le=1.0)
    language: str = Field(default="", max_length=32)
    requires_sandbox_exec: bool = Field(
        default=False,
        description="True if a real sandbox run would be needed (HITL before exec).",
    )


class CoderTaskResult(TaskResult):
    """TaskResult с типизированным output для Coder."""

    output: CoderOutput | None = None
