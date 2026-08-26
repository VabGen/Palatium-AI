"""WorkflowExecutionPolicy — honest collapse of multi_step_workflow."""

from __future__ import annotations

from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy

_PLANS = {
    "knowledge_request": "research pass",
    "tool_execution": "tool pass",
    "clarification_needed": "ask",
    "multi_step_workflow": "unused",
    "social_conversation": "ack",
    "capability_discovery": "caps",
    "response_formatting": "format",
}


def test_multi_step_collapses_to_knowledge_without_mcp() -> None:
    assert (
        WorkflowExecutionPolicy.executable_task_kind("multi_step_workflow", requires_mcp=False) == "knowledge_request"
    )


def test_multi_step_collapses_to_tool_with_mcp() -> None:
    assert WorkflowExecutionPolicy.executable_task_kind("multi_step_workflow", requires_mcp=True) == "tool_execution"


def test_other_kinds_unchanged() -> None:
    assert (
        WorkflowExecutionPolicy.executable_task_kind("social_conversation", requires_mcp=False) == "social_conversation"
    )


def test_plan_text_does_not_claim_multi_step_decomposition() -> None:
    plan = WorkflowExecutionPolicy.plan_for(
        "multi_step_workflow",
        requires_mcp=False,
        default_plans=_PLANS,  # type: ignore[arg-type]
    )
    assert "not decomposable" in plan
    assert "knowledge_request" in plan
    assert "несколько" not in plan.lower()
