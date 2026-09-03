# tests/unit/test_intent_classifier.py

"""Тесты IntentClassifierAgent (BaseAgent + Harness)."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_bridge import intent_output_to_task_result, intent_to_agent_input
from palatium_ai.domain.agents.intent import IntentClassifierInput
from tests.conftest import FakeLLMPort


async def _classify(llm: FakeLLMPort, task_input: IntentClassifierInput):
    harness = Harness(llm=llm)
    agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    agent_input = intent_to_agent_input(
        task_input,
        trace_id="trace-1",
        thread_id="thread-1",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return intent_output_to_task_result(
        output,
        task_id=task_input.task_id,
        agent_role=agent.config.role,
    )


@pytest.mark.asyncio
async def test_intent_classifier_success() -> None:
    llm = FakeLLMPort(
        '{"task_kind": "knowledge_request", "requires_mcp": true, "candidate_capabilities": ["search","retrieve"], "confidence": 0.92, "reasoning": "User asks to find data"}',
    )
    result = await _classify(
        llm,
        IntentClassifierInput(task_id="t1", text="Find the Q3 report"),
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output.task_kind == "knowledge_request"
    assert result.output.requires_mcp is True
    assert result.confidence == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_intent_classifier_low_confidence_partial() -> None:
    llm = FakeLLMPort(
        '{"task_kind": "clarification_needed", "requires_mcp": false, "candidate_capabilities": [], "confidence": 0.4, "reasoning": "Ambiguous request"}',
    )
    result = await _classify(
        llm,
        IntentClassifierInput(task_id="t2", text="maybe something"),
    )

    assert result.status == "partial"
    assert result.output is not None
    assert result.output.task_kind == "clarification_needed"


@pytest.mark.asyncio
async def test_intent_classifier_invalid_json_failure() -> None:
    llm = FakeLLMPort("not json at all")
    result = await _classify(
        llm,
        IntentClassifierInput(task_id="t3", text="hello"),
    )

    assert result.status == "failure"
    assert result.output is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_intent_classifier_user_choice_cap_owned_by_policy() -> None:
    llm = FakeLLMPort(
        '{"task_kind":"knowledge_request","requires_mcp":false,"requires_user_choice":false,'
        '"underspecification_kind":"none","candidate_capabilities":["user_choice"],'
        '"confidence":0.91,"reasoning":"menu ask"}',
    )
    result = await _classify(
        llm,
        IntentClassifierInput(task_id="t4", text="pick a topic"),
    )

    assert result.output is not None
    assert result.output.requires_user_choice is True
    assert result.output.task_kind == "clarification_needed"
    assert result.output.underspecification_kind == "discrete_choice"
