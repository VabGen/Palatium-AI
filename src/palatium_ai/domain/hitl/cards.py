# src/palatium_ai/domain/hitl/cards.py

"""Pydantic-контракты HITL-карточек (без UI-строк 1/2/3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from palatium_ai.domain.content import ActionKind, ActionStyle, IconToken

HITLCardStatus = Literal[
    "pending",
    "resolved",
    "expired",
    "escalated",
    "auto_rejected",
    "dead_letter",
]
HITLCardPurpose = Literal["quality_review", "mcp_tool_approval", "user_choice"]

_TTL_MIN_SECONDS = 5 * 60
_TTL_MAX_SECONDS = 30 * 60
_TTL_DEFAULT_SECONDS = 15 * 60


class HITLOption(BaseModel):
    """Один кликабельный выбор на карточке."""

    model_config = {"frozen": True}

    action_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    kind: ActionKind = "custom"
    style: ActionStyle = "secondary"
    icon: IconToken | None = None
    action_token: str = Field(
        default="",
        max_length=128,
        description="HMAC v2 binding card+action+exp+subject+nonce; required on respond.",
    )


class HITLCardView(BaseModel):
    """Server HITL card (secrets only on owner/manager capability GET)."""

    model_config = {"frozen": True}

    card_id: str = Field(min_length=1, max_length=64)
    thread_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    purpose: HITLCardPurpose = "quality_review"
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=2000)
    options: tuple[HITLOption, ...] = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=1.0)
    status: HITLCardStatus = "pending"
    created_at: datetime
    expires_at: datetime
    resolved_action_id: str | None = None
    resolved_at: datetime | None = None
    owner_user_id: str | None = Field(
        default=None,
        max_length=128,
        description="JWT subject that owns the thread; bound into action tokens.",
    )
    org_id: str | None = Field(
        default=None,
        max_length=128,
        description="Tenant for escalated queue scoping.",
    )
    token_nonce: str = Field(
        default="",
        max_length=64,
        description="Rotated on resolve/escalate; invalidates prior action tokens.",
    )
    escalate_to_roles: tuple[str, ...] = Field(
        default=(),
        description="Manager roles notified on high-risk timeout escalation.",
    )
    content_sha256: str | None = Field(
        default=None,
        max_length=64,
        description="SHA-256 of reviewed document (quality_review); set on mint.",
    )

    def without_secrets(self) -> HITLCardView:
        """Public DTO: strip action_token material (history / manager list)."""
        return self.model_copy(
            update={"options": tuple(option.model_copy(update={"action_token": ""}) for option in self.options)}
        )


class HITLResolveRequest(BaseModel):
    """Ответ пользователя по карточке (идемпотентный)."""

    model_config = {"frozen": True}

    action_id: str = Field(min_length=1, max_length=120)
    action_token: str = Field(min_length=32, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    step_up_assertion: str | None = Field(
        default=None,
        max_length=512,
        description="WebAuthn/IdP/HMAC step-up proof for high-risk mcp_tool_approval.",
    )


class HITLResolveResult(BaseModel):
    """Результат серверной обработки ответа."""

    model_config = {"frozen": True}

    card: HITLCardView
    replayed: bool = False
    message: str = ""


def clamp_ttl_seconds(ttl_seconds: int | None = None) -> int:
    """TTL карточки строго в диапазоне 5–30 минут."""
    value = _TTL_DEFAULT_SECONDS if ttl_seconds is None else ttl_seconds
    return max(_TTL_MIN_SECONDS, min(_TTL_MAX_SECONDS, value))


def new_card_id() -> str:
    """Генерирует уникальный card_id."""
    return f"hitl_{uuid4().hex}"


def default_tool_approval_options() -> tuple[HITLOption, ...]:
    """Actions for MCP tool approval before side-effect execution."""
    return (
        HITLOption(
            action_id="approve",
            label="Allow tool call",
            kind="approve",
            style="primary",
            icon="shield",
        ),
        HITLOption(
            action_id="reject",
            label="Deny tool call",
            kind="reject",
            style="danger",
            icon="x",
        ),
    )


def default_review_options() -> tuple[HITLOption, ...]:
    """Стандартные действия для quality-gate review."""
    return (
        HITLOption(
            action_id="approve",
            label="Approve",
            kind="approve",
            style="primary",
            icon="check",
        ),
        HITLOption(
            action_id="reject",
            label="Reject & revise",
            kind="reject",
            style="danger",
            icon="x",
        ),
    )
