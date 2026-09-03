# tests/unit/test_harness.py

"""Harness guardrails (Wave 2)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from pydantic import BaseModel

from palatium_ai.application.agents.harness import Harness
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput


class _Out(BaseModel):
    model_config = {"frozen": True}
    value: str = "ok"


class _DomainAgent(BaseAgent):
    def get_required_context_keys(self) -> list[str]:
        return []

    def get_available_tools(self) -> list[str]:
        return []

    async def run(self, input: AgentInput) -> AgentOutput:
        return AgentOutput(
            task_id=input.task_id,
            status="success",
            confidence=0.95,
            output=_Out(),
        )


_CONFIG = AgentConfig(
    name="intent_classifier",
    role="intent_classifier",
    model_tier="standard",
    allowed_tools=(),
    confidence_threshold=0.7,
)


@pytest.mark.asyncio
async def test_harness_execute_with_guardrails_success() -> None:
    harness = Harness()
    agent = _DomainAgent(harness, _CONFIG)
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="trace-1",
            instruction="hello",
        ),
    )
    assert output.status == "success"
    assert output.confidence == 0.95


@pytest.mark.asyncio
async def test_harness_execute_with_guardrails_blocks_secrets() -> None:
    harness = Harness()
    agent = _DomainAgent(harness, _CONFIG)
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="trace-2",
            instruction="key sk-abcdefghijklmnopqrstuvwxyz123456",
        ),
    )
    assert output.status == "failure"
    assert output.error_message is not None
