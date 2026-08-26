# tests/unit/test_orchestration_foundation.py

"""Тесты orchestration foundation: snapshot, factory и node input builders."""

from __future__ import annotations

from palatium_ai.application.orchestration.node_inputs import (
    build_context_weaver_input,
    build_critic_input,
    build_formatter_input,
    build_researcher_input,
    build_supervisor_input,
)
from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
from palatium_ai.application.services.context_packet_factory import ContextPacketFactory
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.context_weaver import ContextWeaverOutput, ContextWeaverTaskResult
from palatium_ai.domain.agents.critic import CriticOutput, CriticTaskResult
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.supervisor import SupervisorOutput, SupervisorTaskResult
from palatium_ai.domain.mcp.models import ExecutionPlanBundle, ToolExecutionPlan


def _classification_result() -> IntentTaskResult:
    return IntentTaskResult(
        task_id="task-1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.96,
        requires_review=False,
        output=IntentClassifierOutput(
            task_kind="tool_execution",
            requires_mcp=True,
            candidate_capabilities=("search", "documents"),
            confidence=0.96,
            reasoning="Need external document search.",
        ),
    )


def _routing_result() -> SupervisorTaskResult:
    return SupervisorTaskResult(
        task_id="task-1",
        agent_role="supervisor",
        status="success",
        confidence=0.94,
        requires_review=False,
        output=SupervisorOutput(
            route="researcher",
            confidence=0.94,
            target_agent="researcher",
            plan="Resolve capability and call matching MCP tool.",
        ),
    )


def _critic_result() -> CriticTaskResult:
    return CriticTaskResult(
        task_id="task-1",
        agent_role="critic",
        status="success",
        confidence=0.95,
        requires_review=False,
        output=CriticOutput(
            accuracy_score=9,
            safety_score=9,
            requires_review=False,
            summary="Ready",
        ),
    )


def _context_packet() -> ContextPacket:
    return ContextPacket(
        task_id="task-1",
        user_text="Find the contract in EDMS",
        task_kind="tool_execution",
        route="researcher",
        route_plan="Resolve capability and call matching MCP tool.",
        requires_mcp=True,
        candidate_capabilities=("search", "documents"),
        execution_plan=ToolExecutionPlan(
            strategy="direct_tool_call",
            capability="search",
            server_name="edms",
            tool_name="search_documents",
            requires_tool_call=True,
            rationale="Matching MCP tool found.",
        ),
        context_summary="task_kind=tool_execution; route=researcher; capabilities=search, documents; strategy=direct_tool_call",
    )


def _state(*, with_context_bundle: bool) -> dict[str, object]:
    state: dict[str, object] = {
        "task_id": "task-1",
        "user_text": "Find the contract in EDMS",
        "thread_id": "thread-1",
        "classification": _classification_result(),
        "routing": _routing_result(),
        "critic": _critic_result(),
    }
    if with_context_bundle:
        state["context_bundle"] = ContextWeaverTaskResult(
            task_id="task-1",
            agent_role="context_weaver",
            status="success",
            confidence=1.0,
            requires_review=False,
            output=ContextWeaverOutput(
                context_packet=_context_packet(),
                execution_bundle=ExecutionPlanBundle(
                    selected_strategy="direct_tool_call",
                    requires_tool_call=True,
                    steps=(_context_packet().execution_plan,),
                ),
                available_capabilities=("search", "documents"),
            ),
        )
    return state


def test_context_packet_factory_builds_fallback_packet() -> None:
    factory = ContextPacketFactory()

    packet = factory.from_state(
        task_id="task-1",
        user_text="Find the contract in EDMS",
        classification=_classification_result(),
        routing=_routing_result(),
        fallback_strategy="reason_only",
        fallback_rationale="Fallback path",
    )

    assert packet.task_kind == "tool_execution"
    assert packet.route == "researcher"
    assert packet.requires_mcp is True
    assert packet.execution_plan.strategy == "reason_only"
    assert packet.execution_plan.rationale == "Fallback path"


def test_snapshot_collects_normalized_orchestration_view() -> None:
    snapshot = OrchestrationSnapshot.from_state(_state(with_context_bundle=True))

    assert snapshot.task_id == "task-1"
    assert snapshot.thread_id == "thread-1"
    assert snapshot.task_kind == "tool_execution"
    assert snapshot.route == "researcher"
    assert snapshot.selected_strategy == "direct_tool_call"


def test_node_input_builders_use_context_bundle_when_available() -> None:
    state = _state(with_context_bundle=True)
    snapshot = OrchestrationSnapshot.from_state(state)

    supervisor_input = build_supervisor_input(snapshot)
    context_weaver_input = build_context_weaver_input(snapshot)
    researcher_input = build_researcher_input(snapshot, state)
    critic_input = build_critic_input(snapshot, state)
    formatter_input = build_formatter_input(snapshot, state)

    assert supervisor_input.candidate_capabilities == ("search", "documents")
    assert context_weaver_input.route == "researcher"
    assert researcher_input.context_packet.execution_plan.tool_name == "search_documents"
    assert critic_input.context_packet.execution_plan.strategy == "direct_tool_call"
    assert formatter_input.context_packet.execution_plan.server_name == "edms"


def test_node_input_builders_fall_back_without_context_bundle() -> None:
    state = _state(with_context_bundle=False)
    snapshot = OrchestrationSnapshot.from_state(state)

    researcher_input = build_researcher_input(snapshot, state)
    critic_input = build_critic_input(snapshot, state)
    formatter_input = build_formatter_input(snapshot, state)

    assert researcher_input.context_packet.execution_plan.strategy == "reason_only"
    assert critic_input.context_packet.execution_plan.strategy == "reason_only"
    assert formatter_input.context_packet.execution_plan.strategy == "format_only"
