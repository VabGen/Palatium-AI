"""answer_delta SSE emit for early TTFT (worker + formatter path)."""

from __future__ import annotations

from unittest.mock import patch

from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
from palatium_ai.application.orchestration.nodes import _emit_worker_answer_deltas
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge
from palatium_ai.domain.agents.researcher import ResearcherOutput, ResearcherTaskResult


def test_emit_answer_deltas_noop_without_bridge() -> None:
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=None,
    ):
        emit_answer_deltas("ready prose")


def test_emit_answer_deltas_chunks_and_enqueues() -> None:
    bridge = TurnSseBridge()
    long = "word " * 200
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        emit_answer_deltas(long)
    assert bridge.queue.qsize() >= 2
    first = bridge.queue.get_nowait()
    assert first["event"] == "answer_delta"
    assert isinstance(first["delta"], str)
    assert first["delta"]
    assert "replace" not in first
    joined = first["delta"]
    while not bridge.queue.empty():
        joined += bridge.queue.get_nowait()["delta"]
    assert joined == long.strip()
    assert bridge.has_emitted_answer is True
    assert bridge.sse_ttft_recorded is True


def test_emit_answer_deltas_replace_on_second_emit() -> None:
    bridge = TurnSseBridge()
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        emit_answer_deltas("first draft")
        emit_answer_deltas("revised draft")
    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    assert events[0]["delta"] == "first draft"
    assert "replace" not in events[0]
    assert events[1]["delta"] == "revised draft"
    assert events[1].get("replace") is True


def test_emit_answer_deltas_skips_blank() -> None:
    bridge = TurnSseBridge()
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        emit_answer_deltas("   ")
    assert bridge.queue.empty()


def test_emit_worker_answer_deltas_from_success_result() -> None:
    bridge = TurnSseBridge()
    result = ResearcherTaskResult(
        task_id="t1",
        agent_role="researcher",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=ResearcherOutput(summary="Worker prose ready.", confidence=0.9),
    )
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        _emit_worker_answer_deltas(AgentGraphState(presentation_owner="worker"), result)
    assert bridge.queue.get_nowait()["delta"] == "Worker prose ready."


def test_emit_worker_answer_deltas_skips_failure() -> None:
    bridge = TurnSseBridge()
    result = ResearcherTaskResult(
        task_id="t1",
        agent_role="researcher",
        status="failure",
        confidence=0.0,
        requires_review=True,
        output=ResearcherOutput(summary="partial", confidence=0.0),
        error="boom",
    )
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        _emit_worker_answer_deltas(AgentGraphState(presentation_owner="worker"), result)
    assert bridge.queue.empty()
