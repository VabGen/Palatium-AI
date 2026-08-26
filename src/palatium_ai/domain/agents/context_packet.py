# src/palatium_ai/domain/agents/context_packet.py

"""Нормализованный context packet для передачи между orchestration слоями."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.models import ToolExecutionPlan

from .intent import TaskKind
from .supervisor import WorkerRoute


class ContextPacket(BaseModel):
    """Единый packet для планирования и исполнения."""

    model_config = {"frozen": True}

    task_id: str
    user_text: str = Field(min_length=1, max_length=32_000)
    task_kind: TaskKind
    route: WorkerRoute
    route_plan: str = Field(min_length=1)
    requires_mcp: bool
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    execution_plan: ToolExecutionPlan
    context_summary: str = Field(min_length=1)
