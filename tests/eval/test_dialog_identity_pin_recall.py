# tests/eval/test_dialog_identity_pin_recall.py

"""P1: identity pins survive last-K trim so name recall stays grounded (065).

Deterministic Select-side contract: when the intro turn falls out of the dialog
window, scratchpad/memory hints must still appear as synthetic ``user:`` lines
in the prompt block that Contextualizer / Critic consume.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.domain.memory.budget import MemoryPromptBudget, clip_memory_hints
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow

_IDENTITY = "привет меня зовут геннадий а тебя как?"
_ASK = "как меня зовут?"


def _long_window(*, noise_turns: int = 14) -> DialogTurnWindow:
    """Simulate a thread where the intro was dropped by a 12-turn Select window."""
    now = datetime.now(UTC)
    turns: list[DialogTurn] = []
    for index in range(noise_turns):
        role = "user" if index % 2 == 0 else "assistant"
        turns.append(
            DialogTurn(
                id=uuid4(),
                thread_id="th-id-pin",
                role=role,  # type: ignore[arg-type]
                content=f"noise turn {index}: план на день без имени",
                seq=index + 1,
                created_at=now,
            )
        )
    turns.append(
        DialogTurn(
            id=uuid4(),
            thread_id="th-id-pin",
            role="user",
            content=_ASK,
            seq=noise_turns + 1,
            created_at=now,
        )
    )
    return DialogTurnWindow(thread_id="th-id-pin", turns=tuple(turns[-12:]), limit=12)


def test_name_recall_across_trimmed_dialog_keeps_identity_pin() -> None:
    window = _long_window()
    assert all("геннадий" not in turn.content.casefold() for turn in window.turns)

    budget = MemoryPromptBudget()
    hints = clip_memory_hints((_IDENTITY,), max_items=budget.memory_max_items, max_chars=budget.memory_max_chars)
    block = window.as_prompt_block(
        max_chars=budget.dialog_max_chars,
        per_turn_max_chars=budget.per_turn_max_chars,
        user_turn_max_chars=budget.user_turn_max_chars,
        pinned_user_texts=hints,
    )

    assert "геннадий" in block.casefold()
    assert block.index("геннадий") < block.index(_ASK)
    assert block.startswith("user: ")


def test_name_pin_not_duplicated_when_still_in_window() -> None:
    now = datetime.now(UTC)
    window = DialogTurnWindow(
        thread_id="th-short",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th-short",
                role="user",
                content=_IDENTITY,
                seq=0,
                created_at=now,
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th-short",
                role="assistant",
                content="привет, геннадий",
                seq=1,
                created_at=now,
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th-short",
                role="user",
                content=_ASK,
                seq=2,
                created_at=now,
            ),
        ),
        limit=12,
    )
    block = window.as_prompt_block(pinned_user_texts=(_IDENTITY,))
    assert block.count(_IDENTITY) == 1
