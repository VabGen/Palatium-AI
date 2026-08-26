"""UserChoiceIntentPolicy — exclusive choice remaps to clarification."""

from __future__ import annotations

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy


def test_user_choice_remaps_knowledge_to_clarification() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        requires_user_choice=True,
        candidate_capabilities=("summarize",),
        confidence=0.9,
        reasoning="user asked for topic options",
    )
    out = UserChoiceIntentPolicy.normalize(raw)
    assert out.task_kind == "clarification_needed"
    assert out.requires_mcp is False
    assert out.requires_user_choice is True
    assert "user_choice" in out.candidate_capabilities


def test_user_choice_cap_alone_triggers_normalize() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        requires_user_choice=False,
        candidate_capabilities=("user_choice",),
        confidence=0.88,
        reasoning="tagged select",
    )
    out = UserChoiceIntentPolicy.normalize(raw)
    assert out.requires_user_choice is True
    assert out.task_kind == "clarification_needed"


def test_tool_execution_keeps_kind_when_choice_flagged() -> None:
    raw = IntentClassifierOutput(
        task_kind="tool_execution",
        requires_mcp=True,
        requires_user_choice=True,
        candidate_capabilities=("tool_call", "user_choice"),
        confidence=0.9,
        reasoning="confirm before tool",
    )
    out = UserChoiceIntentPolicy.normalize(raw)
    assert out.task_kind == "tool_execution"
    assert out.requires_mcp is True


def test_no_choice_passthrough() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        requires_user_choice=False,
        candidate_capabilities=("summarize",),
        confidence=0.9,
        reasoning="plain ask",
    )
    assert UserChoiceIntentPolicy.normalize(raw) is raw
