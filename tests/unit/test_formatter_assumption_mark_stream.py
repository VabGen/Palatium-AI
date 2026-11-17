# tests/unit/test_formatter_assumption_mark_stream.py

"""§4: ASSUMPTION_MARK stream_prefix is the first painted chunk before LLM deltas."""

from __future__ import annotations

import json

from uuid import UUID

import pytest

import palatium_ai.application.agents.formatter.agent as formatter_agent

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.content import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.llm.models import LLMCompletion
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.uncertainty import ASSUMPTION_MARK


class _OrderHarness:
    """Records stream start vs prefix emit order; yields a valid ContentDocument JSON."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        doc = ContentDocument(
            locale="ru-RU",
            meta=DocumentMeta(confidence=0.9, kind="response"),
            blocks=(ParagraphBlock(text="тело ответа без префикса"),),
        )
        self._content = json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)

    async def call_llm(self, *args: object, **kwargs: object) -> LLMCompletion:
        _ = args, kwargs
        return LLMCompletion(content=self._content, model="test")

    async def call_llm_stream(
        self,
        *args: object,
        on_delta: object = None,
        **kwargs: object,
    ) -> LLMCompletion:
        _ = args, kwargs
        self._order.append("llm_stream_start")
        completion = await self.call_llm()
        if callable(on_delta):
            on_delta(completion.content)
        return completion


def _task_input() -> FormatterInput:
    packet = ContextPacket(
        task_id="t-mark",
        user_text="ask",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="r",
        ),
        context_summary="s",
        uncertainty_disposition="default_with_mark",
    )
    return FormatterInput(
        task_id="t-mark",
        context_packet=packet,
        worker_summary="тело ответа без префикса",
        uncertainty_disposition="default_with_mark",
    )


@pytest.mark.asyncio()
async def test_stream_prefix_emitted_before_llm_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def _capture_emit(text: str, *, separator: str = "", keep_whitespace: bool = False) -> None:
        _ = separator
        order.append(f"emit:{text!r}:keep={keep_whitespace}")

    monkeypatch.setattr(formatter_agent, "emit_structured_answer_delta", _capture_emit)
    monkeypatch.setattr(formatter_agent, "_paint_partial_frames", lambda *_a, **_k: True)

    harness = _OrderHarness(order)
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]
    agent_input = AgentInput(
        task_id=UUID(int=2),
        trace_id="t-mark",
        instruction="format",
        context={},
    )
    await agent._run_schema_first_streaming(agent_input, _task_input())

    assert order, "expected prefix emit and/or llm stream"
    assert order[0].startswith("emit:"), f"first event must be prefix emit, got {order}"
    assert ASSUMPTION_MARK in order[0]
    assert "\\n\\n" in order[0], "prefix must keep blank line so ## stays at column 0"
    assert "keep=True" in order[0]
    assert "llm_stream_start" in order
    assert order.index(order[0]) < order.index("llm_stream_start")
