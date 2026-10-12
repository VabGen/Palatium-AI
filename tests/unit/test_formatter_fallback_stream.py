"""Formatter first-token fallback stream (Phase 2)."""

from __future__ import annotations

import asyncio

from unittest.mock import MagicMock

import pytest

import palatium_ai.application.agents.formatter.agent as formatter_agent

from palatium_ai.application.agents.formatter.agent import _first_token_fallback_watch
from palatium_ai.application.agents.formatter.stream_delta import FormatterMarkdownEmitter


@pytest.mark.asyncio()
async def test_formatter_fallback_after_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formatter_agent, "_FIRST_TOKEN_FALLBACK_SECONDS", 0.05)
    bridge = MagicMock()
    bridge.has_emitted_answer = False
    bridge.sse_ttft_recorded = False
    bridge.started_at = 0.0
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    _on_delta, cancel = _first_token_fallback_watch(
        emitter,
        worker_summary="Worker draft that should surface as fallback.",
    )
    await asyncio.sleep(0.15)
    await cancel()

    answer_calls = [
        call.args[0]
        for call in bridge.emit_nowait.call_args_list
        if isinstance(call.args[0], dict) and call.args[0].get("event") == "answer_delta"
    ]
    assert answer_calls
    assert answer_calls[0].get("fallback") is True
    assert answer_calls[0].get("replace") is True


@pytest.mark.asyncio()
async def test_first_token_cancels_fallback() -> None:
    bridge = MagicMock()
    bridge.has_emitted_answer = False
    bridge.sse_ttft_recorded = False
    bridge.started_at = 0.0
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    on_delta, cancel = _first_token_fallback_watch(
        emitter,
        worker_summary="Should not fallback",
    )
    on_delta("Hello")
    await asyncio.sleep(0.05)
    await cancel()

    fallback_calls = [
        call.args[0]
        for call in bridge.emit_nowait.call_args_list
        if isinstance(call.args[0], dict) and call.args[0].get("fallback") is True
    ]
    assert fallback_calls == []
