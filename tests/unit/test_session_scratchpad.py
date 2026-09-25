"""Session scratchpad + recall pin-first (race vs sleep-time MemoryKeeper)."""

from __future__ import annotations

import hashlib
import re

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.scratchpad import SessionScratchpadPolicy
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def _user_turns(thread_id: str, texts: tuple[str, ...]) -> DialogTurnWindow:
    """Short user turns (no assistant) — the shape ``merge_from_dialog`` reads."""
    return DialogTurnWindow(
        thread_id=thread_id,
        turns=tuple(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="user",
                content=text,
                seq=idx,
                created_at=datetime.now(UTC),
            )
            for idx, text in enumerate(texts)
        ),
        limit=len(texts) + 1,
    )


def test_scratchpad_policy_merges_short_user_intents() -> None:
    current = SessionScratchpad(thread_id="t-scratch", slots=())
    long_asst = "import requests\n" + ("x" * 400)
    dialog = DialogTurnWindow(
        thread_id="t-scratch",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="t-scratch",
                role="user",
                content="Хочу на ужин утку",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t-scratch",
                role="assistant",
                content="Ок",
                seq=1,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t-scratch",
                role="user",
                content="write python search code",
                seq=2,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t-scratch",
                role="assistant",
                content=long_asst,
                seq=3,
                created_at=datetime.now(UTC),
            ),
        ),
        limit=12,
    )
    updated = SessionScratchpadPolicy.merge_from_dialog(current, dialog)
    blob = " ".join(s.text.lower() for s in updated.slots)
    assert "утк" in blob
    assert "python" in blob


def test_scratchpad_policy_reupsert_moves_existing_slot_to_newest() -> None:
    """A repeated intent refreshes its slot instead of duplicating it (newest wins)."""
    repeat = "Хочу на ужин утку"
    key = SessionScratchpadPolicy.slot_key(repeat)
    current = SessionScratchpad(
        thread_id="t-reupsert",
        slots=(
            ScratchpadSlot(key=key, text=repeat, kind="preference"),
            ScratchpadSlot(key=SessionScratchpadPolicy.slot_key("bring the slides"), text="bring the slides"),
        ),
    )

    updated = SessionScratchpadPolicy.merge_from_dialog(current, _user_turns("t-reupsert", (repeat,)))

    assert [slot.key for slot in updated.slots] == [
        SessionScratchpadPolicy.slot_key("bring the slides"),
        key,
    ]
    assert updated.slots[-1].text == repeat


def test_scratchpad_policy_trims_oldest_slots_beyond_cap() -> None:
    """Slots stay capped at ``max_slots``; the oldest entries drop out."""
    cap = SessionScratchpadPolicy.max_slots
    current = SessionScratchpad(
        thread_id="t-cap",
        slots=tuple(
            ScratchpadSlot(key=SessionScratchpadPolicy.slot_key(f"old intent {idx}"), text=f"old intent {idx}")
            for idx in range(cap)
        ),
    )

    updated = SessionScratchpadPolicy.merge_from_dialog(
        current,
        _user_turns("t-cap", tuple(f"new intent {idx}" for idx in range(cap))),
    )

    assert len(updated.slots) == cap
    texts = [slot.text for slot in updated.slots]
    assert texts == [f"new intent {idx}" for idx in range(cap)]
    assert not any(text.startswith("old intent") for text in texts)


def test_scratchpad_policy_slot_key_falls_back_to_digest_for_unsluggable_text() -> None:
    """Text with no alphanumerics still yields a stable, collision-resistant key."""
    key = SessionScratchpadPolicy.slot_key("??? !!!")
    expected = hashlib.sha256(re.sub(r"\s+", " ", "??? !!!").encode("utf-8")).hexdigest()[:16]

    assert key == f"u:{expected}"
    assert SessionScratchpadPolicy.slot_key("??? !!!") == key


@pytest.mark.asyncio
async def test_scratchpad_survives_anaphoric_recall_without_durable_hit() -> None:
    """Race regression: preference visible on next turn before MemoryKeeper persists."""
    port = InMemoryMemoryPort()
    service = SessionScratchpadService(port)
    dialog = DialogTurnWindow(
        thread_id="t-race",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="t-race",
                role="user",
                content="Хочу на ужин утку",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t-race",
                role="assistant",
                content="Отлично",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
        limit=12,
    )
    await service.refresh_from_dialog(thread_id="t-race", dialog=dialog)
    pad = await service.load(thread_id="t-race")
    assert pad.slots
    assert any("утк" in s.text.lower() for s in pad.slots)

    # Anaphoric query would miss durable memory; scratchpad must still pin the preference.
    recall = await recall_for_thread(
        port,
        thread_id="t-race",
        query="предложи рицепт того что я хотел на ужин",
        limit=4,
        max_chars=800,
        min_confidence=0.7,
        scratchpad=pad,
    )
    hints = " ".join(h.text.lower() for h in recall.hits)
    assert "утк" in hints
    assert recall.hint_texts
    assert any("утк" in t.lower() for t in recall.hint_texts)


@pytest.mark.asyncio
async def test_recall_pins_scratchpad_ahead_of_durable() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=("chat", "thread", "t-pin"),
        key="durable",
        value={"text": "User likes markdown tables", "kind": "preference", "confidence": 0.95},
    )
    pad = SessionScratchpadPolicy.merge_from_dialog(
        SessionScratchpad(thread_id="t-pin", slots=()),
        DialogTurnWindow(
            thread_id="t-pin",
            turns=(
                DialogTurn(
                    id=uuid4(),
                    thread_id="t-pin",
                    role="user",
                    content="Хочу на ужин утку",
                    seq=0,
                    created_at=datetime.now(UTC),
                ),
            ),
            limit=12,
        ),
    )
    recall = await recall_for_thread(
        port,
        thread_id="t-pin",
        query="tables dinner",
        limit=4,
        scratchpad=pad,
    )
    assert recall.hits
    assert "утк" in recall.hits[0].text.lower()
