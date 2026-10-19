"""Contract: at most one SSE frame per turn may reset an already-painted answer.

The "долгая пауза → сырой текст → пауза → замена" regression is a chain of
``replace`` frames that repaint what the user is already reading. Each one is a
layout shift with zero information gain, so the per-turn reset budget is spent
after the single legitimate handover (early worker draft → streamed Formatter
answer). See 040 (observability of the shift) and 055 (contract fix, not a patch).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
from palatium_ai.application.agents.formatter.stream_delta import FormatterMarkdownEmitter
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge
from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy

#: Inputs whose internal identifiers must never reach a delta frame (020).
NO_INTERNAL_TERM_INPUTS: tuple[str, ...] = (
    "Приложи файл attachment_context к запросу.",
    "Смотри prior_context и memory_hints.",
    "Поле context_packet_json заполнено.",
)


class _LayoutShiftSpy:
    def __init__(self) -> None:
        self.records: list[str] = []

    def record_sse_layout_shift(self, *, contract: str) -> None:
        self.records.append(contract)

    def record_sse_ttft(self, *_args: object, **_kwargs: object) -> None:
        return None

    def record_node_execution(self, *_args: object, **_kwargs: object) -> None:
        return None


def _drain(bridge: TurnSseBridge) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    return events


def _replace_frames(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [event for event in events if event.get("event") == "answer_delta" and event.get("replace") is True]


def test_graph_reemit_of_painted_draft_is_skipped() -> None:
    """researcher_node paints the draft; formatter_node re-emits it — must be a no-op."""
    bridge = TurnSseBridge()
    spy = _LayoutShiftSpy()
    with (
        patch(
            "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
            return_value=bridge,
        ),
        patch("palatium_ai.application.agents.formatter.answer_delta.agent_metrics", spy),
    ):
        emit_answer_deltas("Черновик ответа готов.")
        first = _drain(bridge)
        # Re-emit goes through compress_worker_context, so whitespace may differ.
        emit_answer_deltas("Черновик  ответа\nготов.")
        second = _drain(bridge)

    assert len(first) == 1
    assert second == []
    assert _replace_frames(first) == []
    assert spy.records == []


def test_second_reset_is_refused_like_the_contract_says() -> None:
    bridge = TurnSseBridge()
    spy = _LayoutShiftSpy()
    with (
        patch(
            "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
            return_value=bridge,
        ),
        patch("palatium_ai.application.agents.formatter.answer_delta.agent_metrics", spy),
    ):
        emit_answer_deltas("draft one")
        emit_answer_deltas("draft two", replace=True)
        emit_answer_deltas("draft three", replace=True)
        events = _drain(bridge)

    replaces = _replace_frames(events)
    assert len(replaces) == 1
    assert replaces[0]["delta"] == "draft two"
    assert bridge.answer_replaced is True
    # Exactly one real shift, reported once.
    assert spy.records == ["legacy_markdown"]


def test_first_replace_with_nothing_painted_does_not_shift() -> None:
    bridge = TurnSseBridge()
    spy = _LayoutShiftSpy()
    with (
        patch(
            "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
            return_value=bridge,
        ),
        patch("palatium_ai.application.agents.formatter.answer_delta.agent_metrics", spy),
    ):
        emit_answer_deltas("first paint", replace=True)
        events = _drain(bridge)

    assert _replace_frames(events) == []
    assert spy.records == []


def test_formatter_stream_refuses_a_second_reset() -> None:
    """A later stage (repair / locale pass) reopening the emitter must not repaint."""
    bridge = TurnSseBridge()
    spy = _LayoutShiftSpy()
    bridge.has_emitted_answer = True
    bridge.record_answer_frame("worker draft", replace=False)

    with patch("palatium_ai.application.agents.formatter.stream_delta.agent_metrics", spy):
        first = FormatterMarkdownEmitter(bridge=bridge, replace_pending=True)
        first.on_delta("Итог ")
        second = FormatterMarkdownEmitter(bridge=bridge, replace_pending=True)
        second.on_delta("Переписанный итог")
        events = _drain(bridge)

    replaces = _replace_frames(events)
    assert len(replaces) == 1
    assert replaces[0]["delta"] == "Итог "
    assert spy.records == ["legacy_markdown"]


def test_painted_tail_is_bounded() -> None:
    bridge = TurnSseBridge()
    for _ in range(200):
        bridge.record_answer_frame("x" * 512, replace=False)
    assert len(bridge.painted_answer_tail) == 4096


@pytest.mark.parametrize("text", NO_INTERNAL_TERM_INPUTS)
def test_no_internal_term_is_painted_in_any_delta_frame(text: str) -> None:
    """DoD: not a single delta frame may carry an internal contract identifier."""
    bridge = TurnSseBridge()
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)
    # Split mid-term: the emitter must hold the fragment, not paint half of it.
    for index in range(0, len(text), 7):
        emitter.on_delta(text[index : index + 7])
    emitter.finish()

    events = _drain(bridge)
    painted = "".join(str(event.get("content") or event.get("delta") or "") for event in events)
    assert painted
    for frame_text in [str(event.get("content") or event.get("delta") or "") for event in events]:
        assert not InternalVocabularyPolicy.has_terms(frame_text)
