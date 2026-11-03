# tests/unit/test_harness.py

"""Harness guardrails (Wave 2)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from pydantic import BaseModel

from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMUsage,
)


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
# One retry: a failed attempt must be visible without a multi-second backoff chain.
_RETRY_CONFIG = _CONFIG.model_copy(update={"max_retries": 2})


class _FlakyLLM:
    """Fails the first call, answers the retry — the shape a provider blip leaves behind."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: object = None,
        timeout_seconds: float | None = None,
    ) -> LLMCompletion:
        _ = messages, temperature, max_tokens, response_format, response_model, timeout_seconds
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("upstream returned 502")
        return LLMCompletion(
            content="{}",
            model=model or "tier-mid",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )


class _EmptyThenValidLLM:
    """Answers ``200 OK`` with no content, then a valid payload — the observed defect."""

    def __init__(self, *, always_empty: bool = False) -> None:
        self.calls = 0
        self._always_empty = always_empty

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: object = None,
        timeout_seconds: float | None = None,
    ) -> LLMCompletion:
        _ = messages, temperature, max_tokens, response_format, response_model, timeout_seconds
        self.calls += 1
        if self._always_empty or self.calls == 1:
            return LLMCompletion(content="   ", model=model or "tier-small", finish_reason="stop")
        return LLMCompletion(
            content="{}",
            model=model or "tier-small",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
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


@pytest.mark.asyncio()
async def test_call_llm_retries_empty_completion() -> None:
    """``200 OK`` with empty content is retried, not reported as an agent failure.

    Observed with ``response_format=json_object`` on a passed-out provider: the call
    succeeded, nothing was generated, and the raise only happened later in the JSON
    parser — outside the retry loop — so a provider defect became a hard failure
    (``LLMJSONError: No JSON found: ''`` in the researcher trace).
    """
    llm = _EmptyThenValidLLM()
    harness = Harness(llm=llm)
    before = agent_metrics.error_count("intent_classifier", "llm_empty_response")

    completion = await harness.call_llm(_RETRY_CONFIG, [ChatMessage(role="user", content="hi")])

    assert completion.content == "{}"
    assert llm.calls == 2
    assert agent_metrics.error_count("intent_classifier", "llm_empty_response") == before + 1


@pytest.mark.asyncio()
async def test_call_llm_empty_completion_exhausts_retries_as_agent_error() -> None:
    """Every attempt empty → typed ``AgentExecutionError``, never a silent empty answer."""
    llm = _EmptyThenValidLLM(always_empty=True)
    harness = Harness(llm=llm)

    with pytest.raises(AgentExecutionError):
        await harness.call_llm(_RETRY_CONFIG, [ChatMessage(role="user", content="hi")])

    assert llm.calls == 2


@pytest.mark.asyncio()
async def test_call_llm_records_retried_attempt() -> None:
    """A failed attempt leaves a log+metric, so a slow hop is distinguishable from a cold one.

    Without it the harness only exposes the final outcome: "14 s intent_classifier" could be
    a cold provider, a retried 5xx, or a single slow completion (040 — every call is visible).
    """
    llm = _FlakyLLM()
    harness = Harness(llm=llm)
    before = agent_metrics.error_count("intent_classifier", "llm_attempt_failed")

    completion = await harness.call_llm(_RETRY_CONFIG, [ChatMessage(role="user", content="hi")])

    assert completion.content == "{}"
    assert llm.calls == 2
    assert agent_metrics.error_count("intent_classifier", "llm_attempt_failed") == before + 1
