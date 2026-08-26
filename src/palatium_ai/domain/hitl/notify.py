# src/palatium_ai/domain/hitl/notify.py

"""Out-of-band escalation notices (manager queue is not enough alone)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from palatium_ai.domain.hitl.cards import HITLCardPurpose


class HitlEscalationNotice(BaseModel):
    """Payload for manager OOB notify after high-risk TTL escalate."""

    model_config = {"frozen": True}

    card_id: str = Field(min_length=1, max_length=64)
    thread_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    purpose: HITLCardPurpose
    org_id: str | None = None
    risk_score: float = Field(ge=0.0, le=1.0)
    escalate_to_roles: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=200)


class HitlNotifierPort(Protocol):
    """Deliver escalation alerts outside the HTTP queue API."""

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """Best-effort notify; failures should be logged by the adapter, not crash sweep."""


class HitlNotifyPolicy:
    """Decide when OOB notify is required (pure)."""

    @classmethod
    def should_notify_on_escalate(cls, *, risk_score: float, purpose: HITLCardPurpose) -> bool:
        """Notify managers for any escalated card (already past risk threshold policy)."""
        _ = cls
        _ = risk_score
        _ = purpose
        return True
