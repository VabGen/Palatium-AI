"""MemoryRecallPolicy — durable recall gate for low-risk turns."""

from __future__ import annotations

from palatium_ai.domain.policies import MemoryRecallPolicy


def test_skip_social() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="social_conversation", requires_mcp=False)
    assert decision.allowed is False
    assert decision.reason.startswith("skip:")


def test_recall_knowledge() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="knowledge_request", requires_mcp=False)
    assert decision.allowed is True


def test_requires_mcp_forces_recall() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="social_conversation", requires_mcp=True)
    assert decision.allowed is True
    assert decision.reason == "requires_mcp"


def test_unknown_task_kind_fail_closed_to_recall() -> None:
    decision = MemoryRecallPolicy.decide(task_kind=None, requires_mcp=False)
    assert decision.allowed is True
    assert decision.reason == "unknown_task_kind"
