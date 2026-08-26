"""HITL timeout escalation policy (risk → manager queue)."""

from __future__ import annotations

from palatium_ai.domain.hitl.escalation_policy import HitlDeadLetterPolicy, HitlTimeoutPolicy


def test_high_risk_escalates_to_manager_roles() -> None:
    decision = HitlTimeoutPolicy.on_expiry(
        risk_score=0.51,
        manager_roles=frozenset({"manager", "admin"}),
    )
    assert decision.outcome == "escalate"
    assert decision.reason == "high_risk_timeout"
    assert decision.escalate_to_roles == ("admin", "manager")


def test_high_risk_without_roles_still_escalates_fail_closed() -> None:
    decision = HitlTimeoutPolicy.on_expiry(risk_score=0.9, manager_roles=())
    assert decision.outcome == "escalate"
    assert decision.reason == "high_risk_no_manager_roles_configured"
    assert decision.escalate_to_roles == ()


def test_low_risk_auto_rejects() -> None:
    decision = HitlTimeoutPolicy.on_expiry(
        risk_score=0.5,
        manager_roles=frozenset({"manager"}),
    )
    assert decision.outcome == "auto_reject"
    assert decision.reason == "low_risk_timeout"
    assert decision.escalate_to_roles == ()


def test_manager_ttl_expiry_dead_letters_without_reescalate() -> None:
    decision = HitlDeadLetterPolicy.on_manager_ttl_expiry()
    assert decision.outcome == "dead_letter"
    assert decision.reason == "manager_ttl_unresolved"
