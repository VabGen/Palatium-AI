"""Supervisor + ExecutionPlanner routing for social_conversation."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.supervisor_agent import SupervisorAgent
from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.supervisor import SupervisorInput


@pytest.mark.asyncio
async def test_supervisor_routes_social_to_formatter() -> None:
    result = await SupervisorAgent().execute(
        SupervisorInput(
            task_id="t1",
            user_text="привет",
            task_kind="social_conversation",
            requires_mcp=False,
            candidate_capabilities=(),
            classification_confidence=0.95,
        ),
        AgentContext(thread_id="th1"),
    )
    assert result.output is not None
    assert result.output.route == "formatter"
    assert result.output.target_agent == "formatter"


@pytest.mark.asyncio
async def test_supervisor_social_with_mcp_goes_researcher() -> None:
    result = await SupervisorAgent().execute(
        SupervisorInput(
            task_id="t2",
            user_text="привет, найди документ",
            task_kind="social_conversation",
            requires_mcp=True,
            candidate_capabilities=("search",),
            classification_confidence=0.9,
        ),
        AgentContext(thread_id="th2"),
    )
    assert result.output is not None
    assert result.output.route == "researcher"


@pytest.mark.asyncio
async def test_planner_ack_only_for_social_formatter_route() -> None:
    bundle = await ExecutionPlanner().build(
        ContextWeaverInput(
            task_id="t3",
            user_text="спасибо",
            task_kind="social_conversation",
            route="formatter",
            route_plan="Short social reply",
            requires_mcp=False,
            candidate_capabilities=(),
        )
    )
    assert bundle.selected_strategy == "ack_only"
    assert bundle.requires_tool_call is False


@pytest.mark.asyncio
async def test_planner_skips_mcp_discovery_on_formatter_route() -> None:
    """Even with requires_mcp=True, formatter route must not fan-out tools/list."""
    bundle = await ExecutionPlanner().build(
        ContextWeaverInput(
            task_id="t4",
            user_text="привет",
            task_kind="social_conversation",
            route="formatter",
            route_plan="Short social reply",
            requires_mcp=True,
            candidate_capabilities=("search",),
        )
    )
    assert bundle.selected_strategy == "format_only"
    assert bundle.requires_tool_call is False


@pytest.mark.asyncio
async def test_supervisor_multi_step_routes_researcher_with_honest_plan() -> None:
    result = await SupervisorAgent().execute(
        SupervisorInput(
            task_id="t-ms",
            user_text="сделай пайплайн из трёх шагов",
            task_kind="multi_step_workflow",
            requires_mcp=False,
            candidate_capabilities=(),
            classification_confidence=0.9,
        ),
        AgentContext(thread_id="th-ms"),
    )
    assert result.output is not None
    assert result.output.route == "researcher"
    assert "not decomposable" in result.output.plan
    assert "нескольких шагов" not in result.output.plan


@pytest.mark.asyncio
async def test_planner_multi_step_is_single_retrieve_pass() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(
        ContextWeaverInput(
            task_id="t-ms2",
            user_text="pipeline",
            task_kind="multi_step_workflow",
            route="researcher",
            route_plan="collapsed",
            requires_mcp=False,
            candidate_capabilities=(),
        )
    )
    assert len(bundle.steps) == 1
    assert bundle.selected_strategy == "retrieve_then_reason"
    assert bundle.requires_tool_call is False


@pytest.mark.asyncio
async def test_planner_requires_mcp_without_tool_fails_closed_strategy() -> None:
    """requires_mcp without a resolved tool must not invent retrieve_then_reason drafts."""
    bundle = await ExecutionPlanner(capability_index=None).build(
        ContextWeaverInput(
            task_id="t5",
            user_text="что такое RAG?",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="Research",
            requires_mcp=True,
            candidate_capabilities=("search",),
        )
    )
    assert bundle.selected_strategy == "reason_only"
    assert bundle.requires_tool_call is False
    assert "fail closed" in bundle.steps[0].rationale
