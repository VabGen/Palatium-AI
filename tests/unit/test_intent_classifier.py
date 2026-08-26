# tests/unit/test_intent_classifier.py

"""Тесты IntentClassifierAgent."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.intent_classifier_agent import IntentClassifierAgent
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.intent import IntentClassifierInput
from tests.conftest import FakeLLMPort


@pytest.mark.asyncio
async def test_intent_classifier_success() -> None:
    llm = FakeLLMPort(
        '{"task_kind": "knowledge_request", "requires_mcp": true, "candidate_capabilities": ["search","retrieve"], "confidence": 0.92, "reasoning": "User asks to find data"}',
    )
    agent = IntentClassifierAgent(llm)
    result = await agent.execute(
        IntentClassifierInput(task_id="t1", text="Find the Q3 report"),
        AgentContext(thread_id="thread-1"),
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
    agent = IntentClassifierAgent(llm)
    result = await agent.execute(
        IntentClassifierInput(task_id="t2", text="maybe something"),
        AgentContext(thread_id="thread-2"),
    )

    assert result.status == "partial"
    assert result.output is not None
    assert result.output.task_kind == "clarification_needed"


@pytest.mark.asyncio
async def test_intent_classifier_invalid_json_failure() -> None:
    llm = FakeLLMPort("not json at all")
    agent = IntentClassifierAgent(llm)
    result = await agent.execute(
        IntentClassifierInput(task_id="t3", text="hello"),
        AgentContext(thread_id="thread-3"),
    )

    assert result.status == "failure"
    assert result.output is None
    assert result.error is not None
