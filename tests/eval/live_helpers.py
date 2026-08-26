# tests/eval/live_helpers.py

"""Helpers for opt-in live memory eval (real LLM)."""

from __future__ import annotations

import os

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow

LIVE_ENV = "PALATIUM_LIVE_EVAL"


def live_eval_enabled() -> bool:
    """True when operator explicitly opted into network/LLM eval."""
    return os.environ.get(LIVE_ENV, "").strip().lower() in {"1", "true", "yes"}


require_live = pytest.mark.skipif(
    not live_eval_enabled(),
    reason=f"Set {LIVE_ENV}=1 to run live LongMemEval against a real LLM",
)


def dialog_pair(
    *,
    thread_id: str,
    user_text: str,
    assistant_text: str,
) -> DialogTurnWindow:
    """Two-turn window for Contextualizer live cases."""
    return DialogTurnWindow(
        thread_id=thread_id,
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="user",
                content=user_text,
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="assistant",
                content=assistant_text,
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
