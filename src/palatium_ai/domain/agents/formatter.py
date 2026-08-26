# src/palatium_ai/domain/agents/formatter.py

"""Контракты агента Formatter."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.contracts import TaskResult
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.hitl.cards import HITLCardView

# Canonical structured answer (no markdown fallback field).
FormatterOutput = ContentDocument

# Stable failure code when LLM output cannot be validated as ContentDocument.
FORMATTER_OUTPUT_INVALID = "formatter_output_invalid"


class FormatterInput(BaseModel):
    """Вход Formatter агента."""

    model_config = {"frozen": True}

    task_id: str
    context_packet: ContextPacket
    worker_summary: str | None = None
    critic_summary: str | None = None
    requires_review: bool = False
    revision_feedback: str | None = Field(default=None, max_length=4_000)


class FormatterTaskResult(TaskResult):
    """TaskResult с ContentDocument и серверными HITL-карточками."""

    output: ContentDocument | None = None
    hitl_cards: tuple[HITLCardView, ...] = Field(default_factory=tuple)
