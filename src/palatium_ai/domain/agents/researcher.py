# src/palatium_ai/domain/agents/researcher.py

"""Контракты агента Researcher."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .context_packet import ContextPacket
from .contracts import TaskResult

# Stable failure when planned MCP args cannot be built/validated.
RESEARCHER_TOOL_ARGS_INVALID = "researcher_tool_args_invalid"


class ResearcherInput(BaseModel):
    """Вход Researcher агента."""

    model_config = {"frozen": True}

    task_id: str
    context_packet: ContextPacket
    prior_context: str | None = Field(default=None, max_length=16_000)
    mcp_tool_output_max_chars: int = Field(default=3000, ge=500, le=16_000)
    revision_feedback: str | None = Field(default=None, max_length=4_000)


class ResearcherOutput(BaseModel):
    """Результат аналитического/поискового ответа."""

    model_config = {"frozen": True}

    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    sources_used: tuple[str, ...] = Field(default_factory=tuple)


class ResearcherTaskResult(TaskResult):
    """TaskResult с типизированным output для Researcher."""

    output: ResearcherOutput | None = None
