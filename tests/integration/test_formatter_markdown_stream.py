"""Integration: Formatter Hybrid stream emits text_delta + dual answer_delta, parses MD."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.content import ICON_NAME_SET, CalloutBlock, ContentDocument, HeadingBlock
from palatium_ai.domain.llm.models import LLMCompletion
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task_input() -> FormatterInput:
    return FormatterInput(
        task_id="00000000-0000-0000-0000-000000000001",
        context_packet=ContextPacket(
            task_id="00000000-0000-0000-0000-000000000001",
            user_text="status?",
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
        ),
        worker_summary="Done. No errors.",
        response_locale="en-US",
    )


@pytest.mark.asyncio()
async def test_formatter_markdown_stream_dual_emit_and_document() -> None:
    markdown = "> [!SUCCESS]\n> No errors.\n"
    harness = AsyncMock()

    async def _stream(*_args: object, **kwargs: object) -> LLMCompletion:
        on_delta = kwargs.get("on_delta")
        assert callable(on_delta)
        # Simulate token stream
        for piece in ("> [!SUCCESS]\n", "> No errors.\n"):
            on_delta(piece)
        return LLMCompletion(content=markdown, model="test")

    harness.call_llm_stream = AsyncMock(side_effect=_stream)
    harness.call_llm = AsyncMock()
    agent = FormatterAgent(harness, FORMATTER_CONFIG)

    bridge = TurnSseBridge()
    bridge.has_emitted_answer = True  # worker draft already shown
    task = _task_input()
    context = {
        "context_packet_json": task.context_packet.model_dump_json(),
        "worker_summary": task.worker_summary or "",
        "critic_summary": "",
        "requires_review": "false",
        "requires_user_choice": "false",
        "underspecification_kind": "none",
        "revision_feedback": "",
        "response_locale": "en-US",
    }
    from uuid import UUID

    with turn_sse_bridge(bridge):
        output = await agent.run(
            AgentInput(
                task_id=UUID("00000000-0000-0000-0000-000000000001"),
                trace_id="tr",
                instruction="format",
                context=context,
            )
        )

    assert output.status in {"success", "partial"}
    assert isinstance(output.output, ContentDocument)
    assert isinstance(output.output.blocks[0], CalloutBlock)

    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    assert events[0]["event"] == "text_delta"
    assert events[1] == {
        "event": "answer_delta",
        "delta": "> [!SUCCESS]\n",
        "replace": True,
    }
    assert any(e.get("event") == "text_delta" for e in events)
    # Only the first dual answer_delta carries replace.
    replace_flags = [e for e in events if e.get("event") == "answer_delta" and e.get("replace")]
    assert len(replace_flags) == 1
    harness.call_llm_stream.assert_awaited()
    assert harness.call_llm_stream.await_args.kwargs["response_format"] == "text"


@pytest.mark.asyncio()
async def test_formatter_stream_strips_emoji_from_sse_and_document() -> None:
    markdown = '# <icon name="document"/> Title\n\nRisk ⚠️ here 📞.\n'
    harness = AsyncMock()

    async def _stream(*_args: object, **kwargs: object) -> LLMCompletion:
        on_delta = kwargs.get("on_delta")
        assert callable(on_delta)
        on_delta(markdown)
        return LLMCompletion(content=markdown, model="test")

    harness.call_llm_stream = AsyncMock(side_effect=_stream)
    harness.call_llm = AsyncMock()
    agent = FormatterAgent(harness, FORMATTER_CONFIG)
    bridge = TurnSseBridge()
    task = _task_input()
    context = {
        "context_packet_json": task.context_packet.model_dump_json(),
        "worker_summary": task.worker_summary or "",
        "critic_summary": "",
        "requires_review": "false",
        "requires_user_choice": "false",
        "underspecification_kind": "none",
        "revision_feedback": "",
        "response_locale": "en-US",
    }
    from uuid import UUID

    with turn_sse_bridge(bridge):
        output = await agent.run(
            AgentInput(
                task_id=UUID("00000000-0000-0000-0000-000000000001"),
                trace_id="tr",
                instruction="format",
                context=context,
            )
        )

    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    sse_blob = "".join(
        str(e.get("content") or e.get("delta") or "")
        for e in events
        if e.get("event") in {"text_delta", "answer_delta"}
    )
    assert "⚠" not in sse_blob
    assert "📞" not in sse_blob
    assert "📄" not in sse_blob
    assert "<icon" not in sse_blob

    assert isinstance(output.output, ContentDocument)
    prose = output.output.plain_text()
    assert "⚠" not in prose
    assert "📞" not in prose
    for block in output.output.blocks:
        icon = getattr(block, "icon", None)
        assert icon is None or icon in ICON_NAME_SET
        if isinstance(block, HeadingBlock):
            assert block.icon == "document"
