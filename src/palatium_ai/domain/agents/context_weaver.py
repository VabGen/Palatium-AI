# src/palatium_ai/domain/agents/context_weaver.py

"""Контракты агента ContextWeaver."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.models import ExecutionPlanBundle

from .context_packet import ContextPacket
from .contracts import TaskResult
from .intent import TaskKind
from .supervisor import WorkerRoute


class ContextWeaverInput(BaseModel):
    """Вход ContextWeaver агента."""

    model_config = {"frozen": True}

    task_id: str
    user_text: str = Field(min_length=1, max_length=32_000)
    task_kind: TaskKind
    route: WorkerRoute
    route_plan: str = Field(min_length=1)
    requires_mcp: bool
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)


class ContextWeaverOutput(BaseModel):
    """Собранный контекст и execution plan для worker layer."""

    model_config = {"frozen": True}

    context_packet: ContextPacket
    execution_bundle: ExecutionPlanBundle
    available_capabilities: tuple[str, ...] = Field(default_factory=tuple)


class ContextWeaverTaskResult(TaskResult):
    """TaskResult с типизированным output для ContextWeaver."""

    output: ContextWeaverOutput | None = None
