"""Formatter first-token fallback stream (Phase 2)."""

from __future__ import annotations

import asyncio

import pytest

import palatium_ai.application.agents.formatter.agent as formatter_agent

from palatium_ai.application.agents.formatter.agent import _first_token_fallback_watch
from palatium_ai.application.agents.formatter.stream_delta import FormatterMarkdownEmitter
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge


def _answer_frames(bridge: TurnSseBridge) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    return [event for event in events if event.get("event") == "answer_delta"]


@pytest.mark.asyncio()
async def test_formatter_fallback_after_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formatter_agent, "_FIRST_TOKEN_FALLBACK_SECONDS", 0.05)
    bridge = TurnSseBridge()
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    _on_delta, cancel = _first_token_fallback_watch(
        emitter,
        worker_summary="Worker draft that should surface as fallback.",
    )
    await asyncio.sleep(0.15)
    await cancel()

    answer_calls = _answer_frames(bridge)
    assert answer_calls
    assert answer_calls[0].get("fallback") is True
    # Nothing was painted before this frame, so there is nothing to replace.
    assert "replace" not in answer_calls[0]


@pytest.mark.asyncio()
async def test_formatter_fallback_skips_already_painted_draft() -> None:
    """A draft the user already reads must not be re-painted by the watchdog."""
    bridge = TurnSseBridge()
    bridge.has_emitted_answer = True
    bridge.record_answer_frame("Worker draft that should surface as fallback.", replace=False)
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    emitter.emit_fallback_prose("Worker draft that should surface as fallback.")

    assert _answer_frames(bridge) == []
    # Real Formatter tokens still take over the painted draft.
    assert emitter.replace_pending is True


@pytest.mark.asyncio()
async def test_formatter_fallback_replaces_painted_other_draft() -> None:
    bridge = TurnSseBridge()
    bridge.has_emitted_answer = True
    bridge.record_answer_frame("An older revision of the draft.", replace=False)
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    emitter.emit_fallback_prose("Worker draft that should surface as fallback.")

    frames = _answer_frames(bridge)
    assert len(frames) == 1
    assert frames[0].get("fallback") is True
    assert frames[0].get("replace") is True
    assert bridge.answer_replaced is True


@pytest.mark.asyncio()
async def test_first_token_cancels_fallback() -> None:
    bridge = TurnSseBridge()
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)

    on_delta, cancel = _first_token_fallback_watch(
        emitter,
        worker_summary="Should not fallback",
    )
    on_delta("Hello")
    await asyncio.sleep(0.05)
    await cancel()

    assert [event for event in _answer_frames(bridge) if event.get("fallback") is True] == []
