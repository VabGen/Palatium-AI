# tests/unit/test_extract_admission_policy.py

"""Extract admission contract (060, 055): axes decide, not phrases or length."""

from __future__ import annotations

import pytest

from palatium_ai.domain.policies import ExtractAdmissionDecision, ExtractAdmissionPolicy


@pytest.mark.parametrize("task_kind", ("social_conversation", "clarification_needed"))
def test_non_recallable_task_kind_is_skipped(task_kind: str) -> None:
    decision = ExtractAdmissionPolicy.decide(task_kind=task_kind, strategy="format_only")

    assert decision == ExtractAdmissionDecision(admit=False, reason=f"task_kind:{task_kind}")


@pytest.mark.parametrize("strategy", ("ack_only", "format_only", "clarify"))
def test_non_recallable_strategy_is_skipped(strategy: str) -> None:
    decision = ExtractAdmissionPolicy.decide(task_kind="knowledge_request", strategy=strategy)

    assert decision.admit is False
    assert decision.reason == f"strategy:{strategy}"


@pytest.mark.parametrize("task_kind", ("knowledge_request", "multi_step_workflow", "tool_execution"))
def test_substantive_kinds_are_admitted(task_kind: str) -> None:
    decision = ExtractAdmissionPolicy.decide(task_kind=task_kind, strategy="retrieve_then_reason")

    assert decision.admit is True
    assert decision.reason == "admitted"


def test_missing_axes_admit() -> None:
    """Absent classification must not silently stop learning from a turn (fail-open)."""
    assert ExtractAdmissionPolicy.decide(task_kind=None, strategy=None).admit is True
    assert ExtractAdmissionPolicy.decide(task_kind="", strategy="").admit is True


def test_short_substantive_turn_is_admitted() -> None:
    """A short preference ("отвечай по-русски") is recallable; length is not the signal."""
    decision = ExtractAdmissionPolicy.decide(task_kind="knowledge_request", strategy="reason_only")

    assert decision.admit is True
