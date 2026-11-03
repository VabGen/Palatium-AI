# src/palatium_ai/domain/agents/context_packet.py

"""Нормализованный context packet для передачи между orchestration слоями."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.types import (
    ATTACHMENT_SCOPE_DEFAULT,
    GROUNDING_DEFAULT,
    RESPONSE_SHAPE_DEFAULT,
    AttachmentScope,
    GroundingMode,
    ResponseShape,
)

from .intent import TaskKind
from .supervisor import WorkerRoute

# Hard ceiling for fenced attachment text in one turn. The prompt budget policy
# (065) may shrink this further; the field cap exists so a malformed caller
# cannot push an unbounded string into the graph state / checkpoint (050).
_MAX_UNTRUSTED_CONTEXT_CHARS = 60_000


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
    grounding: GroundingMode = Field(default=GROUNDING_DEFAULT)
    grounding_reason: str = Field(default="", max_length=500)
    #: Requested form of the answer body (auto = Formatter chooses). Presentation only:
    #: never selects a route or a tool (ADR 0005, 055).
    response_shape: ResponseShape = Field(default=RESPONSE_SHAPE_DEFAULT)
    execution_plan: ToolExecutionPlan
    context_summary: str = Field(min_length=1)
    #: Plurality of a thread-file ask (Intent axis). ``all`` = every file of the dialog;
    #: the worker expands it into one owner-scoped read per file (055).
    attachment_scope: AttachmentScope = Field(default=ATTACHMENT_SCOPE_DEFAULT)
    #: Attachment text for this turn, already wrapped in the untrusted fence by
    #: AttachmentService. Empty means "no attachments" (020, 065).
    untrusted_context: str = Field(default="", max_length=_MAX_UNTRUSTED_CONTEXT_CHARS)
    local_retrieval_empty: bool = Field(
        default=False,
        description="True when local knowledge/memory search returned no hits; enables web_fallback.",
    )
