# src/palatium_ai/domain/hitl/risk_policy.py

"""Purpose-aware risk scores for HITL cards (escalation / TTL behaviour)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.hitl.action_tokens import MANAGER_TOKEN_SUBJECT

if TYPE_CHECKING:
    from palatium_ai.domain.content import ActionSpec


class HitlRiskPolicy:
    """Derive risk_score from card purpose and action specs — not UX hardcodes."""

    CHOICE_FLOOR = 0.25
    CONFIRM_FLOOR = 0.5
    MCP_WRITE_FLOOR = 0.55

    @classmethod
    def for_choice(cls, actions: tuple[ActionSpec, ...] | list[ActionSpec]) -> float:
        """Menu / confirm choices: max(action.risk_score, purpose floor)."""
        if not actions:
            return cls.CHOICE_FLOOR
        peak = max(float(action.risk_score) for action in actions)
        kinds = {action.kind for action in actions}
        floor = cls.CONFIRM_FLOOR if kinds & {"confirm", "approve", "reject"} else cls.CHOICE_FLOOR
        return max(0.0, min(1.0, max(peak, floor)))

    @classmethod
    def for_quality(cls, confidence: float) -> float:
        """Quality gate: inverse confidence."""
        return max(0.0, min(1.0, 1.0 - confidence))

    @classmethod
    def for_mcp_tool(cls, risk_score: float) -> float:
        """MCP approval: never score write/unknown below MCP_WRITE_FLOOR."""
        return max(0.0, min(1.0, max(float(risk_score), cls.MCP_WRITE_FLOOR)))

    @classmethod
    def binding_subject(cls, *, owner_user_id: str | None, escalated: bool = False) -> str:
        """Token subject: owner for pending; manager role marker after escalate."""
        _ = cls
        if escalated:
            return MANAGER_TOKEN_SUBJECT
        return (owner_user_id or "").strip()
