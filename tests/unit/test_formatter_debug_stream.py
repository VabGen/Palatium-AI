"""Formatter streams GFM as text_delta (+ dual answer_delta) when SSE bridge is bound."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion


def _completion(content: str = "Hello") -> LLMCompletion:
    return LLMCompletion(content=content, model="test")


def _agent() -> tuple[FormatterAgent, AsyncMock]:
    harness = AsyncMock()
    harness.call_llm = AsyncMock(return_value=_completion())
    harness.call_llm_stream = AsyncMock(return_value=_completion())
    return FormatterAgent(harness, FORMATTER_CONFIG), harness


@pytest.mark.asyncio()
async def test_formatter_one_shot_text_without_bridge() -> None:
    agent, harness = _agent()
    messages = [ChatMessage(role="user", content="hi")]
    _completion_out, markdown = await agent._call_formatter_llm(messages, max_tokens=32)
    assert markdown == "Hello"
    harness.call_llm.assert_awaited_once()
    kwargs = harness.call_llm.await_args.kwargs
    assert kwargs["response_format"] == "text"
    assert kwargs["response_model"] is None
    harness.call_llm_stream.assert_not_awaited()


@pytest.mark.asyncio()
async def test_formatter_streams_text_delta_and_dual_answer_delta() -> None:
    agent, harness = _agent()

    async def _stream(*_args: object, **kwargs: object) -> LLMCompletion:
        on_delta = kwargs["on_delta"]
        assert callable(on_delta)
        on_delta("Hello ")
        on_delta("world")
        return _completion("Hello world")

    harness.call_llm_stream = AsyncMock(side_effect=_stream)
    bridge = TurnSseBridge()
    messages = [ChatMessage(role="user", content="hi")]
    with turn_sse_bridge(bridge):
        completion, markdown = await agent._call_formatter_llm(messages, max_tokens=32)
    assert markdown == "Hello world"
    assert completion.content == "Hello world"
    harness.call_llm.assert_not_awaited()
    kwargs = harness.call_llm_stream.await_args.kwargs
    assert kwargs["response_format"] == "text"
    assert kwargs["response_model"] is None

    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    assert events == [
        {"event": "text_delta", "content": "Hello "},
        {"event": "answer_delta", "delta": "Hello "},
        {"event": "text_delta", "content": "world"},
        {"event": "answer_delta", "delta": "world"},
    ]
    assert bridge.has_emitted_answer is True


@pytest.mark.asyncio()
async def test_formatter_replace_once_after_worker_draft() -> None:
    agent, harness = _agent()

    async def _stream(*_args: object, **kwargs: object) -> LLMCompletion:
        on_delta = kwargs["on_delta"]
        assert callable(on_delta)
        on_delta("Final")
        return _completion("Final")

    harness.call_llm_stream = AsyncMock(side_effect=_stream)
    bridge = TurnSseBridge()
    bridge.has_emitted_answer = True
    messages = [ChatMessage(role="user", content="hi")]
    with turn_sse_bridge(bridge):
        await agent._call_formatter_llm(messages, max_tokens=32)

    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    assert events[0] == {"event": "text_delta", "content": "Final"}
    assert events[1] == {"event": "answer_delta", "delta": "Final", "replace": True}
