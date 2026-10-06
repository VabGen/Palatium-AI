# tests/unit/test_harness.py

"""Harness guardrails (Wave 2)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from pydantic import BaseModel

from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.observability.metrics import agent_metrics
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


class _CapturingAgent(_DomainAgent):
    """Records the context the agent actually saw after harness sanitisation."""

    def __init__(self, harness: Harness, config: AgentConfig) -> None:
        super().__init__(harness, config)
        self.seen: AgentInput | None = None

    async def run(self, input: AgentInput) -> AgentOutput:
        self.seen = input
        return await super().run(input)


_CONFIG = AgentConfig(
    name="intent_classifier",
    role="intent_classifier",
    model_tier="mid",
    allowed_tools=(),
    confidence_threshold=0.7,
)


@pytest.mark.asyncio()
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


@pytest.mark.asyncio()
async def test_harness_execute_with_guardrails_redacts_instruction_secret() -> None:
    """A credential in the instruction is masked, not hard-failed (thread stays usable)."""
    harness = Harness()
    agent = _CapturingAgent(harness, _CONFIG)
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="trace-2",
            instruction="key sk-abcdefghijklmnopqrstuvwxyz123456",
        ),
    )
    assert output.status == "success"
    assert agent.seen is not None
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in agent.seen.instruction
    assert "[REDACTED]" in agent.seen.instruction
    assert agent_metrics.secret_redaction_count("intent_classifier", "instruction") >= 1


@pytest.mark.asyncio()
async def test_harness_execute_with_guardrails_redacts_context_secret() -> None:
    """Secrets already persisted in dialog history are masked on read, never brick the turn."""
    harness = Harness()
    agent = _CapturingAgent(harness, _CONFIG)
    poisoned = '{"role": "user", "content": "password=hunter2"}'
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="trace-3",
            instruction="продолжай",
            context={"dialog_window_json": poisoned},
        ),
    )
    assert output.status == "success"
    assert agent.seen is not None
    assert "hunter2" not in agent.seen.context["dialog_window_json"]
    assert agent_metrics.secret_redaction_count("intent_classifier", "assembled_context.dialog_window_json") >= 1
