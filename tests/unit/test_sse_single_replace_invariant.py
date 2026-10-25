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
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
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

    def record_sse_first_block(self, *_args: object, **_kwargs: object) -> None:
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


def test_structured_contract_suppresses_the_intermediate_worker_draft() -> None:
    """Nothing replaces a draft under structured_incremental — so it must not be painted."""
    from palatium_ai.application.orchestration.nodes import _emit_worker_answer_deltas
    from palatium_ai.domain.agents.researcher import ResearcherOutput, ResearcherTaskResult

    result = ResearcherTaskResult(
        task_id="t1",
        agent_role="researcher",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=ResearcherOutput(summary="Черновик сравнения.", confidence=0.9),
    )
    legacy = TurnSseBridge(stream_contract="legacy_markdown")
    structured = TurnSseBridge(stream_contract="structured_incremental")
    state: AgentGraphState = {"presentation_owner": "worker"}

    with turn_sse_bridge(legacy):
        _emit_worker_answer_deltas(state, result)
    with turn_sse_bridge(structured):
        _emit_worker_answer_deltas(state, result)

    assert _drain(legacy) != []
    assert _drain(structured) == []
    assert structured.has_emitted_answer is False


def test_formatter_owned_turn_never_paints_the_worker_draft() -> None:
    """A draft the Formatter rewrites would be replaced — the single-writer contract forbids it."""
    from palatium_ai.application.orchestration.nodes import _emit_worker_answer_deltas
    from palatium_ai.domain.agents.researcher import ResearcherOutput, ResearcherTaskResult

    result = ResearcherTaskResult(
        task_id="t1",
        agent_role="researcher",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=ResearcherOutput(summary="Черновик для переписывания.", confidence=0.9),
    )
    bridge = TurnSseBridge(stream_contract="legacy_markdown")
    state: AgentGraphState = {"presentation_owner": "formatter"}

    with turn_sse_bridge(bridge):
        _emit_worker_answer_deltas(state, result)

    assert _drain(bridge) == []
    assert bridge.has_emitted_answer is False


def test_structured_fragments_append_and_never_replace() -> None:
    from palatium_ai.application.agents.formatter.answer_delta import emit_structured_answer_delta

    bridge = TurnSseBridge(stream_contract="structured_incremental")
    spy = _LayoutShiftSpy()
    with turn_sse_bridge(bridge), patch("palatium_ai.application.agents.formatter.answer_delta.agent_metrics", spy):
        emit_structured_answer_delta("Первый блок.")
        emit_structured_answer_delta("Первый блок.", separator="\n\n")  # legit repeat
        emit_structured_answer_delta("Второй блок.", separator="\n\n")
        frames = _drain(bridge)

    assert _replace_frames(frames) == []
    assert "".join(str(frame["delta"]) for frame in frames) == ("Первый блок.\n\nПервый блок.\n\nВторой блок.")
    assert spy.records == []


def test_structured_block_frames_are_typed_sanitized_and_append_only() -> None:
    """block_delta carries the same typed payload the final BlockRenderer consumes."""
    from palatium_ai.application.agents.formatter.answer_delta import emit_document_block
    from palatium_ai.domain.content import CodeBlock, ParagraphBlock

    bridge = TurnSseBridge(stream_contract="structured_incremental")
    spy = _LayoutShiftSpy()
    with turn_sse_bridge(bridge), patch("palatium_ai.application.agents.formatter.answer_delta.agent_metrics", spy):
        emit_document_block(index=0, block=ParagraphBlock(text="Смотри memory_hints."))
        emit_document_block(index=1, block=CodeBlock(language="python", content="prior_context = 1"))
        frames = _drain(bridge)

    assert [frame["event"] for frame in frames] == ["block_delta", "block_delta"]
    assert all("replace" not in frame for frame in frames)
    assert frames[0]["index"] == 0
    assert frames[0]["block"]["text"] == "Смотри память о вас."
    # Code is user content, not prose: the guard must not rewrite it (055).
    assert frames[1]["block"]["content"] == "prior_context = 1"
    assert spy.records == []
    assert bridge.sse_ttft_recorded is True


def test_stream_contract_follows_the_formatter_two_key_rollout() -> None:
    from palatium_ai.application.services.intent_service import IntentService

    service = object.__new__(IntentService)
    service._formatter_mode = "schema_first"
    service._formatter_rollout_pct = 100
    assert service._stream_contract("user-1") == "structured_incremental"

    service._formatter_rollout_pct = 0
    assert service._stream_contract("user-1") == "legacy_markdown"

    service._formatter_mode = "legacy"
    service._formatter_rollout_pct = 100
    assert service._stream_contract("user-1") == "legacy_markdown"


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
