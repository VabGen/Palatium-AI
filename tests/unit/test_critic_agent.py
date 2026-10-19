"""Critic uses provider structured output (response_model), not manual coercion."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticOutput
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.llm.models import LLMCompletion
from palatium_ai.domain.mcp.models import ToolExecutionPlan


class _CapturingHarness:
    """Captures the call_llm kwargs and returns a schema-shaped JSON body."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.kwargs: dict[str, object] = {}

    async def call_llm(self, config: object, messages: object, **kwargs: object) -> LLMCompletion:
        _ = config, messages
        self.kwargs = kwargs
        return LLMCompletion(content=self._content, model="stub")


def _packet() -> ContextPacket:
    return ContextPacket(
        task_id="t1",
        user_text="What is the contract status?",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="research then answer",
        requires_mcp=False,
        candidate_capabilities=("summarize",),
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="reason",
        ),
        context_summary="reason_only",
    )


def _agent_input(packet: ContextPacket) -> AgentInput:
    return AgentInput(
        task_id=uuid4(),
        trace_id="trace-critic",
        instruction="judge",
        context={
            "context_packet_json": packet.model_dump_json(),
            "selected_strategy": "reason_only",
            "continuation_kind": "new_topic",
            "classification_confidence": "0.9",
            "classification_reasoning": "knowledge",
            "worker_summary": "Contract is signed",
        },
    )


@pytest.mark.asyncio()
async def test_critic_uses_response_model() -> None:
    """Critic requests json_schema with CriticOutput and validates it via the model."""
    harness = _CapturingHarness('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
    agent = CriticAgent(harness, CRITIC_CONFIG)  # type: ignore[arg-type]

    result = await agent.run(_agent_input(_packet()))

    assert harness.kwargs.get("response_model") is CriticOutput
    assert harness.kwargs.get("response_format") == "json_schema"
    assert isinstance(result.output, CriticOutput)
    assert result.output.accuracy_score == 9
    assert result.output.requires_review is False
    assert result.status == "success"
