"""Intent axis + graph routing for chat memory mutations (E2E-01/03)."""

from __future__ import annotations

import json

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.application.orchestration.nodes import route_after_intent
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult


def _payload(**overrides: object) -> str:
    base: dict[str, object] = {
        "task_kind": "knowledge_request",
        "requires_mcp": False,
        "requires_user_choice": False,
        "underspecification_kind": "none",
        "candidate_capabilities": [],
        "grounding": "optional",
        "grounding_reason": "",
        "transformation": "none",
        "file_reference": "none",
        "response_shape": "auto",
        "memory_mutation": "none",
        "memory_text": "",
        "memory_key": "",
        "confidence": 0.9,
        "reasoning": "test",
    }
    base.update(overrides)
    return json.dumps(base)


def _classification(**overrides: object) -> IntentTaskResult:
    output = IntentClassifierOutput(
        task_kind="tool_execution",
        requires_mcp=True,
        confidence=0.9,
        reasoning="test",
        **overrides,
    )
    return IntentTaskResult(
        task_id="task-1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        output=output,
    )


def test_parse_save_mutation_forces_tool_execution() -> None:
    output = parse_classifier_output(
        _payload(
            memory_mutation="save",
            memory_text="порт базы 5433",
            memory_key="db_port",
            requires_user_choice=True,
            underspecification_kind="discrete_choice",
        )
    )
    assert output.memory_mutation == "save"
    assert output.memory_text == "порт базы 5433"
    assert output.memory_key == "db_port"
    # An execution is never a menu, and it always needs the MCP write path (070).
    assert output.task_kind == "tool_execution"
    assert output.requires_mcp is True
    assert output.requires_user_choice is False
    assert output.underspecification_kind == "none"


def test_parse_mutation_without_payload_is_none() -> None:
    output = parse_classifier_output(_payload(memory_mutation="forget", memory_text="   "))
    assert output.memory_mutation == "none"
    assert output.task_kind == "knowledge_request"


def test_route_after_intent_sends_mutation_to_gate() -> None:
    state = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "classification": _classification(memory_mutation="save", memory_text="x"),
    }
    assert route_after_intent(state) == "memory_mutation"


def test_route_after_intent_keeps_normal_flow() -> None:
    state = {"task_id": "task-1", "thread_id": "thread-1", "classification": _classification()}
    assert route_after_intent(state) == "context_enricher_continuation"
