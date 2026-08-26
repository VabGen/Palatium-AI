"""In-memory dialog turn store behavior used by tests (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


class _FakeDialogTurnStore:
    def __init__(self) -> None:
        self._turns: dict[str, list[DialogTurn]] = {}

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
    ) -> DialogTurn:
        seq = len(self._turns.get(thread_id, []))
        turn = DialogTurn(
            id=uuid4(),
            thread_id=thread_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            task_id=task_id,
            seq=seq,
            created_at=datetime.now(UTC),
        )
        self._turns.setdefault(thread_id, []).append(turn)
        return turn

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        items = self._turns.get(thread_id, [])[-limit:]
        return DialogTurnWindow(thread_id=thread_id, turns=tuple(items), limit=limit)


@pytest.mark.asyncio
async def test_fake_dialog_store_orders_turns() -> None:
    store = _FakeDialogTurnStore()
    await store.append_turn(thread_id="t", role="user", content="a")
    await store.append_turn(thread_id="t", role="assistant", content="b")
    window = await store.list_recent_turns(thread_id="t", limit=10)
    assert [turn.role for turn in window.turns] == ["user", "assistant"]
    assert window.as_prompt_block().startswith("user:")
