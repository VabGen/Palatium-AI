# src/palatium_ai/domain/agents/messages.py

"""Контракты AgentInput / AgentOutput (030) — единственный источник."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.llm.models import ImagePart


class AgentInput(BaseModel):
    """Вход агента после JIT-сборки контекста Harness'ом."""

    model_config = {"frozen": True}

    task_id: UUID
    trace_id: str
    instruction: str
    context: dict[str, str] = Field(default_factory=dict)
    #: Images the agent may look at this turn (ADR 0007), already admitted by
    #: ``VisionImageService`` — a worker never decides that an upload is safe to send.
    #: References, not bytes: the blob store stays the single owner of the payload, so
    #: the message contract cannot copy an upload into logs, traces or a checkpoint (020).
    #: ``ImagePart`` is reused instead of a second ``AttachmentPayload`` DTO: id + closed
    #: mime vocabulary are already the domain contract, and a parallel type would drift
    #: from the one the adapter validates (050). Empty default keeps every pre-existing
    #: caller (graph bridges, eval cassettes, unit agents) valid without a shim (010).
    image_parts: tuple[ImagePart, ...] = ()


class AgentOutput(BaseModel):
    """Структурированный выход агента; output — подтип, объявленный агентом."""

    model_config = {"frozen": True}

    task_id: UUID
    status: Literal["success", "failure", "partial"]
    confidence: float = Field(ge=0.0, le=1.0)
    output: BaseModel
    error_message: str | None = None
