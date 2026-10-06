# tests/unit/test_parallel_workers.py

"""P2.15: ParallelWorkerPolicy + multi-step planner + graph route."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from palatium_ai.application.orchestration.nodes import (
    route_after_context,
    route_after_quality_revision,
)
from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.core.types.graph_nodes import (
    NODE_ANALYST,
    NODE_PARALLEL_WORKERS,
    NODE_RESEARCHER,
)
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.parallel_workers import ParallelWorkerPolicy


def test_policy_caps_require_both_research_and_analytics() -> None:
    yes = ParallelWorkerPolicy.decide_from_capabilities(
        candidate_capabilities=("search", "analytics"),
    )
    assert yes.parallel is True
    no = ParallelWorkerPolicy.decide_from_capabilities(
        candidate_capabilities=("search",),
    )
    assert no.parallel is False


def test_policy_steps_require_both_strategies() -> None:
    steps = (
        ToolExecutionPlan(
            strategy="retrieve_then_reason",
            requires_tool_call=True,
            rationale="r",
            server_name="platform",
            tool_name="search_knowledge",
        ),
        ToolExecutionPlan(strategy="data_analysis", requires_tool_call=False, rationale="a"),
    )
    assert ParallelWorkerPolicy.decide_from_steps(steps).parallel is True
    assert (
        ParallelWorkerPolicy.decide_from_steps(
            (ToolExecutionPlan(strategy="data_analysis", requires_tool_call=False, rationale="a"),)
        ).parallel
        is False
    )


@pytest.mark.asyncio()
async def test_planner_emits_two_steps_for_multi_cap() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(
        ContextWeaverInput(
            task_id="t-par",
            user_text="find docs and analyze trends",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="multi",
            requires_mcp=False,
            candidate_capabilities=("knowledge", "analytics"),
        )
    )
    assert len(bundle.steps) == 2
    strategies = {s.strategy for s in bundle.steps}
    assert "retrieve_then_reason" in strategies
    assert "data_analysis" in strategies
    assert bundle.selected_strategy == "retrieve_then_reason"


def _snapshot(strategy: str) -> MagicMock:
    snap = MagicMock()
    snap.selected_strategy = strategy
    return snap


def test_route_after_context_parallel_workers() -> None:
    steps = (
        ToolExecutionPlan(
            strategy="retrieve_then_reason",
            requires_tool_call=True,
            rationale="r",
            server_name="platform",
            tool_name="search_knowledge",
        ),
        ToolExecutionPlan(strategy="data_analysis", requires_tool_call=False, rationale="a"),
    )
    state: dict = {"requires_clarification": False}
    with (
        patch(
            "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
            side_effect=lambda _s: _snapshot("retrieve_then_reason"),
        ),
        patch(
            "palatium_ai.application.orchestration.nodes.selectors.execution_plan_steps",
            return_value=steps,
        ),
    ):
        assert route_after_context(state) == NODE_PARALLEL_WORKERS  # type: ignore[arg-type]


def test_route_after_quality_revision_parallel() -> None:
    steps = (
        ToolExecutionPlan(
            strategy="retrieve_then_reason",
            requires_tool_call=True,
            rationale="r",
            server_name="platform",
            tool_name="search_knowledge",
        ),
        ToolExecutionPlan(strategy="data_analysis", requires_tool_call=False, rationale="a"),
    )
    with patch(
        "palatium_ai.application.orchestration.nodes.selectors.execution_plan_steps",
        return_value=steps,
    ):
        assert route_after_quality_revision({}) == NODE_PARALLEL_WORKERS  # type: ignore[arg-type]


def test_route_single_analyst_unchanged() -> None:
    state: dict = {"requires_clarification": False}
    with (
        patch(
            "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
            side_effect=lambda _s: _snapshot("data_analysis"),
        ),
        patch(
            "palatium_ai.application.orchestration.nodes.selectors.execution_plan_steps",
            return_value=(ToolExecutionPlan(strategy="data_analysis", requires_tool_call=False, rationale="a"),),
        ),
    ):
        assert route_after_context(state) == NODE_ANALYST  # type: ignore[arg-type]


def test_route_single_researcher_unchanged() -> None:
    state: dict = {"requires_clarification": False}
    with (
        patch(
            "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
            side_effect=lambda _s: _snapshot("reason_only"),
        ),
        patch(
            "palatium_ai.application.orchestration.nodes.selectors.execution_plan_steps",
            return_value=(ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="r"),),
        ),
    ):
        assert route_after_context(state) == NODE_RESEARCHER  # type: ignore[arg-type]
