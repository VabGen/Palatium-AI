"""HITL timeout / escalation policy (risk → escalate vs auto-reject)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EscalationOutcome = Literal["escalate", "auto_reject"]
DeadLetterOutcome = Literal["dead_letter"]


class TimeoutEscalationDecision(BaseModel):
    """Outcome of HITL card TTL expiry."""

    model_config = {"frozen": True}

    outcome: EscalationOutcome
    reason: str = Field(min_length=1, max_length=128)
    escalate_to_roles: tuple[str, ...] = ()


class DeadLetterDecision(BaseModel):
    """Outcome when an escalated card's manager TTL expires unresolved."""

    model_config = {"frozen": True}

    outcome: DeadLetterOutcome = "dead_letter"
    reason: str = Field(min_length=1, max_length=128)


class HitlTimeoutPolicy:
    """Pure domain policy: risk_score > 0.5 → manager escalation queue."""

    RISK_ESCALATION_THRESHOLD = 0.5

    @classmethod
    def on_expiry(
        cls,
        *,
        risk_score: float,
        manager_roles: frozenset[str] | tuple[str, ...],
    ) -> TimeoutEscalationDecision:
        """Decide escalate vs auto-reject for an expired pending card."""
        roles = tuple(sorted(role for role in manager_roles if role.strip()))
        if risk_score > cls.RISK_ESCALATION_THRESHOLD:
            if not roles:
                # Fail closed: still escalate status, but signal missing manager routing.
                return TimeoutEscalationDecision(
                    outcome="escalate",
                    reason="high_risk_no_manager_roles_configured",
                    escalate_to_roles=(),
                )
            return TimeoutEscalationDecision(
                outcome="escalate",
                reason="high_risk_timeout",
                escalate_to_roles=roles,
            )
        return TimeoutEscalationDecision(
            outcome="auto_reject",
            reason="low_risk_timeout",
            escalate_to_roles=(),
        )


class HitlDeadLetterPolicy:
    """Pure domain policy: escalated + manager TTL expiry → terminal dead_letter.

    Does not re-escalate (avoids infinite OOB notify loops). Ops must monitor
    ``hitl_card_dead_letter`` / queue age before the second TTL fires.
    """

    @classmethod
    def on_manager_ttl_expiry(cls) -> DeadLetterDecision:
        """Close unresolved escalated cards after the manager window."""
        _ = cls
        return DeadLetterDecision(
            outcome="dead_letter",
            reason="manager_ttl_unresolved",
        )
