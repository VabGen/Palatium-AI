"""Raw formatter JSON is not an SSE event unless debug streaming is enabled."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.core.config.formatter import FormatterConfig
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion


def _settings(*, debug: bool) -> SimpleNamespace:
    return SimpleNamespace(formatter=FormatterConfig(debug_stream_deltas=debug))


def _completion() -> LLMCompletion:
    return LLMCompletion(content="{}", model="test")


def _agent() -> tuple[FormatterAgent, AsyncMock]:
    harness = AsyncMock()
    harness.call_llm = AsyncMock(return_value=_completion())
    harness.call_llm_stream = AsyncMock(return_value=_completion())
    return FormatterAgent(harness, FORMATTER_CONFIG), harness


@pytest.mark.asyncio()
async def test_formatter_does_not_emit_json_deltas_by_default() -> None:
    agent, harness = _agent()
    bridge = TurnSseBridge()
    messages = [ChatMessage(role="user", content="hi")]
    settings = _settings(debug=False)
    with (
        patch("palatium_ai.core.config.get_settings", return_value=settings),
        turn_sse_bridge(bridge),
    ):
        await agent._call_formatter_llm(messages, max_tokens=32)
    harness.call_llm.assert_awaited_once()
    kwargs = harness.call_llm.await_args.kwargs
    assert kwargs["response_format"] == "json_schema"
    assert kwargs["response_model"].__name__ == "ContentDocument"
    harness.call_llm_stream.assert_not_awaited()
    assert bridge.queue.empty()


@pytest.mark.asyncio()
async def test_formatter_emits_json_deltas_when_debug_flag_is_on() -> None:
    agent, harness = _agent()

    async def _stream(*_args: object, **kwargs: object) -> LLMCompletion:
        on_delta = kwargs["on_delta"]
        assert callable(on_delta)
        await on_delta('{"schema_version":1}')
        return _completion()

    harness.call_llm_stream = AsyncMock(side_effect=_stream)
    settings = _settings(debug=True)
    bridge = TurnSseBridge()
    messages = [ChatMessage(role="user", content="hi")]
    with (
        patch("palatium_ai.core.config.get_settings", return_value=settings),
        turn_sse_bridge(bridge),
    ):
        await agent._call_formatter_llm(messages, max_tokens=32)
    harness.call_llm.assert_not_awaited()
    kwargs = harness.call_llm_stream.await_args.kwargs
    assert kwargs["response_format"] == "json_schema"
    assert kwargs["response_model"].__name__ == "ContentDocument"
    event = bridge.queue.get_nowait()
    assert event == {"event": "formatter_delta", "delta": '{"schema_version":1}'}
