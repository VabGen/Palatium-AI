"""MemoryRecallPolicy — durable recall gate for low-risk turns."""

from __future__ import annotations

from palatium_ai.domain.policies import MemoryRecallPolicy


def test_social_recalls_preferences_only() -> None:
    """Social turns personalise (name, tone) but never pull task facts."""
    decision = MemoryRecallPolicy.decide(task_kind="social_conversation", requires_mcp=False)
    assert decision.allowed is True
    assert decision.kinds == ("preference",)


def test_clarification_needed_still_recalls() -> None:
    """Regression: history-blind clarify skipped recall, so Continuity had no memory to
    recover from the false clarify (``memory_recall.skipped reason=skip:clarification_needed``)."""
    decision = MemoryRecallPolicy.decide(task_kind="clarification_needed", requires_mcp=False)
    assert decision.allowed is True
    assert decision.kinds is None


def test_skip_response_formatting() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="response_formatting", requires_mcp=False)
    assert decision.allowed is False


def test_capability_discovery_preference_only() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="capability_discovery", requires_mcp=False)
    assert decision.allowed is True
    assert decision.kinds == ("preference",)
    assert "preference" in decision.reason


def test_recall_knowledge() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="knowledge_request", requires_mcp=False)
    assert decision.allowed is True
    assert decision.kinds is None


def test_requires_mcp_forces_recall() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="social_conversation", requires_mcp=True)
    assert decision.allowed is True
    assert decision.reason == "requires_mcp"


def test_unknown_task_kind_fail_closed_to_recall() -> None:
    decision = MemoryRecallPolicy.decide(task_kind=None, requires_mcp=False)
    assert decision.allowed is True
    assert decision.reason == "unknown_task_kind"


def test_content_transform_recalls_preferences_and_filters_pins() -> None:
    """A rewrite reads the prior answer; pinned asks/facts would re-open the old topic.

    Regression: stale scratchpad pin «сравни файлы» rode every turn as a hint and
    steered «перепиши ответ короче» back into a file comparison (055, 060).
    """
    for transformation in ("shorten", "rewrite", "expand"):
        decision = MemoryRecallPolicy.decide(
            task_kind="knowledge_request",
            requires_mcp=False,
            transformation=transformation,
        )
        assert decision.allowed is True
        assert decision.kinds == ("preference",)
        assert decision.pin_kinds == ("preference",)
        assert decision.reason == f"transform:{transformation}:preference"


def test_restructure_is_not_a_content_transform() -> None:
    decision = MemoryRecallPolicy.decide(
        task_kind="response_formatting",
        requires_mcp=False,
        transformation="restructure",
    )
    assert decision.allowed is False
    assert decision.pin_kinds is None
