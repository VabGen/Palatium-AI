"""Formatter graceful degradation when schema repair is exhausted (Phase 1.1)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.formatter import (
    FORMATTER_CONFIG,
    FormatterAgent,
    repair as repair_module,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.llm.models import LLMCompletion
from palatium_ai.domain.mcp.models import ToolExecutionPlan


class _StubHarness:
    """Minimal HarnessPort: always returns the same plain-text completion."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def call_llm(self, config: object, messages: object, **kwargs: object) -> LLMCompletion:
        _ = config, messages, kwargs
        return LLMCompletion(content=self._content, model="stub")

    async def call_llm_stream(self, config: object, messages: object, **kwargs: object) -> LLMCompletion:
        return await self.call_llm(config, messages, **kwargs)


def _packet(*, user_text: str = "summarize the contract") -> ContextPacket:
    return ContextPacket(
        task_id="t1",
        user_text=user_text,
        task_kind="knowledge_request",
        route="researcher",
        route_plan="reason then answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="reason",
        ),
        context_summary="reason_only",
    )


def _social_packet() -> ContextPacket:
    """Social with no worker draft → ``final_text`` stays empty (nothing to render)."""
    return ContextPacket(
        task_id="t2",
        user_text="привет",
        task_kind="social_conversation",
        route="formatter",
        route_plan="short social reply",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="social",
        ),
        context_summary="format_only",
    )


def _agent_input(packet: ContextPacket, *, worker_summary: str) -> AgentInput:
    return AgentInput(
        task_id=uuid4(),
        trace_id="trace-formatter-fallback",
        instruction="format",
        context={
            "context_packet_json": packet.model_dump_json(),
            "worker_summary": worker_summary,
            "response_locale": "en-US",
        },
    )


@pytest.mark.asyncio()
async def test_parse_errors_fall_back_to_worker_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repair exhausted + worker draft present → deterministic fallback, not an empty doc."""

    def _always_invalid(*_args: object, **_kwargs: object) -> object:
        raise ValueError("markdown never becomes a ContentDocument")

    monkeypatch.setattr(repair_module, "markdown_to_content_document", _always_invalid)

    agent = FormatterAgent(_StubHarness("garbage that never parses"), FORMATTER_CONFIG)
    result = await agent.run(_agent_input(_packet(), worker_summary="Пример осмысленного ответа."))

    assert result.status in {"partial", "success"}
    assert result.output.blocks, "должен быть непустой ContentDocument"
    assert result.output.meta.confidence > 0.0, "не должен быть invalid_output с 0.0"


@pytest.mark.asyncio()
async def test_no_source_still_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repair exhausted and no source (empty worker + empty user_text) → honest failure."""

    def _always_invalid(*_args: object, **_kwargs: object) -> object:
        raise ValueError("markdown never becomes a ContentDocument")

    monkeypatch.setattr(repair_module, "markdown_to_content_document", _always_invalid)

    agent = FormatterAgent(_StubHarness("garbage that never parses"), FORMATTER_CONFIG)
    result = await agent.run(_agent_input(_social_packet(), worker_summary=""))

    assert result.status == "failure"
    assert result.output.meta.confidence == 0.0
    assert result.output.meta.requires_review is True
    assert result.output.blocks == ()
