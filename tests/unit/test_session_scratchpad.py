"""Session scratchpad + recall pin-first (race vs sleep-time MemoryKeeper)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.domain.memory.scratchpad import SessionScratchpad
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.scratchpad import SessionScratchpadPolicy
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


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
