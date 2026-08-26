"""Unit tests for Contextualizer / dialog prompt budgets."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.domain.memory.budget import clip_memory_hints
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


def test_dialog_window_total_char_budget() -> None:
    turns = tuple(
        DialogTurn(
            id=uuid4(),
            thread_id="th",
            role="assistant",
            content="x" * 900,
            seq=idx,
            created_at=datetime.now(UTC),
        )
        for idx in range(5)
    )
    window = DialogTurnWindow(thread_id="th", turns=turns)
    block = window.as_prompt_block(max_chars=1500, per_turn_max_chars=500)
    assert len(block) <= 1500


def test_user_turns_keep_longer_payload_than_assistant() -> None:
    """Pastes are task payloads — do not clip user turns to chat-assistant budget."""
    now = datetime.now(UTC)
    window = DialogTurnWindow(
        thread_id="th",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th",
                role="user",
                content="U" * 5_000,
                seq=0,
                created_at=now,
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th",
                role="assistant",
                content="A" * 5_000,
                seq=1,
                created_at=now,
            ),
        ),
    )
    block = window.as_prompt_block(
        max_chars=20_000,
        per_turn_max_chars=500,
        user_turn_max_chars=4_000,
    )
    assert "U" * 3_500 in block
    assert "A" * 600 not in block
    assert "A" * 400 in block


def test_clip_memory_hints_empty() -> None:
    assert clip_memory_hints(()) == ()


def test_hint_texts_respect_max_chars() -> None:
    hits = (
        MemoryHit(text="a" * 200, kind="fact", confidence=0.9, score=2),
        MemoryHit(text="b" * 200, kind="fact", confidence=0.9, score=1),
    )
    bundle = MemoryRecallBundle(thread_id="t", hits=hits, max_items=4, max_chars=220)
    assert len(bundle.hint_texts) == 1
    assert len(bundle.hint_texts[0]) <= 220
