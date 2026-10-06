"""Regression: new upload fences must not re-inject prior-file answers via selectors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from palatium_ai.application.orchestration.selectors import (
    resolved_prior_assistant_content,
    resolved_worker_summary,
)
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies import EffectiveRoutingIntent

_PRIOR_FILE_A = "Сводка по файлу A: квартальный отчёт, выручка 12 млн."
_FENCE_FILE_B = (
    '<untrusted_content source="attachment:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb:plan.docx">\n'
    "Содержание файла B: план встречи на пятницу.\n"
    "</untrusted_content>"
)


def _dialog_with_file_a_answer() -> DialogTurnWindow:
    return DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="user",
                content="Сделай сводку по файлу",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="assistant",
                content=_PRIOR_FILE_A,
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
        limit=12,
    )


def test_cleared_prior_context_does_not_fall_back_to_dialog() -> None:
    """ContinuityPolicy set prior_context=None; selector must not reload file A."""
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "Сделай сводку по файлу",
            "dialog_window": _dialog_with_file_a_answer(),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                continuation_kind="answer",
                prior_context=None,
                trust_prior_for_workers=False,
                reasoning="continuity=answer; new upload owns evidence",
            ),
        },
    )
    assert resolved_prior_assistant_content(state) is None
    assert resolved_worker_summary(state) is None


def test_untrusted_context_blocks_prior_even_if_intent_had_prior() -> None:
    """Fence for file B owns the turn — prior about file A must not reach workers."""
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "Что в этом файле?",
            "untrusted_context": _FENCE_FILE_B,
            "dialog_window": _dialog_with_file_a_answer(),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                continuation_kind="answer",
                prior_context=_PRIOR_FILE_A,
                trust_prior_for_workers=False,
                reasoning="should not happen after ContinuityPolicy, belt-and-suspenders",
            ),
        },
    )
    assert resolved_prior_assistant_content(state) is None
    assert resolved_worker_summary(state) is None


def test_trusted_prior_still_flows_without_attachments() -> None:
    """Follow-up without upload still binds ContinuityPolicy prior to workers."""
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "Когда завершится встреча?",
            "dialog_window": _dialog_with_file_a_answer(),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                continuation_kind="answer",
                prior_context="Завершение встречи (15:00–15:15)",
                trust_prior_for_workers=True,
                reasoning="answer follow-up",
            ),
        },
    )
    prior = resolved_prior_assistant_content(state)
    assert prior is not None
    assert "15:00" in prior
    summary = resolved_worker_summary(state)
    assert summary is not None
    assert "15:00" in summary


def test_dialog_fallback_when_routing_intent_absent() -> None:
    """Without ContinuityPolicy result, last assistant remains available."""
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "уточни",
            "dialog_window": _dialog_with_file_a_answer(),
        },
    )
    prior = resolved_prior_assistant_content(state)
    assert prior is not None
    assert "файлу A" in prior
