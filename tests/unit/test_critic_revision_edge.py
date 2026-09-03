"""Graph routing: worker strategies + Critic revision edge (bounded)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from palatium_ai.application.orchestration.nodes import (
    route_after_context,
    route_after_critic,
    route_after_quality_revision,
)
from palatium_ai.core.types.graph_nodes import (
    NODE_ANALYST,
    NODE_CODER,
    NODE_FORMATTER,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
)
from palatium_ai.domain.agents.critic import CriticOutput, CriticTaskResult


def _critic(*, requires_review: bool) -> CriticTaskResult:
    return CriticTaskResult(
        task_id="t1",
        agent_role="critic",
        status="partial" if requires_review else "success",
        confidence=0.5,
        requires_review=requires_review,
        output=CriticOutput(
            accuracy_score=3 if requires_review else 9,
            safety_score=9,
            requires_review=requires_review,
            summary="Needs more sources",
        ),
    )


def _snapshot(strategy: str) -> MagicMock:
    snap = MagicMock()
    snap.selected_strategy = strategy
    return snap


def test_route_after_context_dispatches_coder_analyst() -> None:
    state: dict = {"requires_clarification": False}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("code_sandbox"),
    ):
        assert route_after_context(state) == NODE_CODER  # type: ignore[arg-type]
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("data_analysis"),
    ):
        assert route_after_context(state) == NODE_ANALYST  # type: ignore[arg-type]
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("reason_only"),
    ):
        assert route_after_context(state) == NODE_RESEARCHER  # type: ignore[arg-type]


def test_route_after_critic_schedules_revision_under_budget() -> None:
    state = {"critic": _critic(requires_review=True), "revisions_count": 0}
    with (
        patch(
            "palatium_ai.application.orchestration.nodes.max_quality_revisions",
            return_value=2,
        ),
        patch(
            "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
            side_effect=lambda _s: _snapshot("reason_only"),
        ),
    ):
        assert route_after_critic(state) == NODE_QUALITY_REVISION  # type: ignore[arg-type]


def test_route_after_critic_exhausts_to_formatter() -> None:
    state = {"critic": _critic(requires_review=True), "revisions_count": 2}
    with patch(
        "palatium_ai.application.orchestration.nodes.max_quality_revisions",
        return_value=2,
    ):
        assert route_after_critic(state) == NODE_FORMATTER  # type: ignore[arg-type]


def test_route_after_quality_revision_by_strategy() -> None:
    state: dict = {}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("code_sandbox"),
    ):
        assert route_after_quality_revision(state) == NODE_CODER  # type: ignore[arg-type]
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("data_analysis"),
    ):
        assert route_after_quality_revision(state) == NODE_ANALYST  # type: ignore[arg-type]
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("direct_tool_call"),
    ):
        assert route_after_quality_revision(state) == NODE_RESEARCHER  # type: ignore[arg-type]


def test_graph_topology_has_revision_loop() -> None:
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
    from palatium_ai.application.orchestration.graph import build_agent_graph
    from tests.conftest import (
        FakeLLMPort,
        make_analyst_agent,
        make_coder_agent,
        make_continuation_agent,
        make_critic_agent,
        make_formatter_agent,
        make_researcher_agent,
        make_supervisor_agent,
        make_weaving_agent,
    )

    harness = Harness(llm=FakeLLMPort("{}"))
    graph = build_agent_graph(
        harness=harness,
        intent_agent=IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),  # type: ignore[arg-type]
        supervisor_agent=make_supervisor_agent(harness),
        continuation_agent=make_continuation_agent(harness=harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(FakeLLMPort("{}"), harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(FakeLLMPort("{}")),
        formatter_agent=make_formatter_agent(FakeLLMPort("{}")),
    )
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert (NODE_CODER, "critic") in edges
    assert (NODE_ANALYST, "critic") in edges
    targets_from_critic = {e.target for e in graph.get_graph().edges if e.source == "critic"}
    assert NODE_QUALITY_REVISION in targets_from_critic
    assert NODE_FORMATTER in targets_from_critic
    targets_from_rev = {e.target for e in graph.get_graph().edges if e.source == NODE_QUALITY_REVISION}
    assert {NODE_RESEARCHER, NODE_CODER, NODE_ANALYST} <= targets_from_rev
