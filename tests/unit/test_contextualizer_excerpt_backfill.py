"""RC-1: prior_assistant_excerpt backfill for prior-bound kinds only."""

from __future__ import annotations

import json

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.application.agents.context_enricher.continuation.parsing import parse_contextualizer_output
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow

_PRIOR = "Тезисный анализ обращения МБОО «Доброе дело»: предмет, сроки."


def _dialog() -> DialogTurnWindow:
    return DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="user",
                content="дай анализ",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="assistant",
                content=_PRIOR,
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
        limit=12,
    )


def test_answer_kind_backfills_empty_excerpt_from_dialog() -> None:
    raw = json.dumps(
        {
            "rewritten_query": "почему тезисный анализ обращения МБОО?",
            "continuation_kind": "answer",
            "confidence": 0.9,
            "refers_to_prior": True,
            "prior_assistant_excerpt": None,
            "reasoning": "meta about prior",
        },
        ensure_ascii=False,
    )
    out = parse_contextualizer_output(raw, dialog_window=_dialog())
    assert out.prior_assistant_excerpt is not None
    assert "Доброе" in out.prior_assistant_excerpt or "тезисный" in out.prior_assistant_excerpt.lower()


def test_new_topic_does_not_backfill_excerpt() -> None:
    raw = json.dumps(
        {
            "rewritten_query": "Какая погода в Минске?",
            "continuation_kind": "new_topic",
            "confidence": 0.95,
            "refers_to_prior": False,
            "prior_assistant_excerpt": None,
            "reasoning": "independent",
        },
        ensure_ascii=False,
    )
    out = parse_contextualizer_output(raw, dialog_window=_dialog())
    assert out.prior_assistant_excerpt is None
