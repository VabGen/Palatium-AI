"""Edit rewind: SessionTimelineService truncates turns and clears checkpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.session_timeline_service import SessionTimelineService
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


class _Store:
    def __init__(self) -> None:
        self._turns: dict[str, list[DialogTurn]] = {}

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
        payload: dict[str, object] | None = None,
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
            payload=payload,
        )
        self._turns.setdefault(thread_id, []).append(turn)
        return turn

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        items = self._turns.get(thread_id, [])[-limit:]
        return DialogTurnWindow(thread_id=thread_id, turns=tuple(items), limit=limit)

    async def truncate_keeping(self, *, thread_id: str, keep: int) -> int:
        items = self._turns.get(thread_id, [])
        safe_keep = max(0, keep)
        if safe_keep >= len(items):
            return 0
        deleted = len(items) - safe_keep
        self._turns[thread_id] = items[:safe_keep]
        return deleted


class _McpRepo:
    """Unused for truncate path; satisfies constructor."""


@pytest.mark.asyncio()
async def test_truncate_dialog_turns_clears_checkpoints() -> None:
    store = _Store()
    cleared: list[str] = []

    async def clear_checkpoints(*, thread_id: str) -> int:
        cleared.append(thread_id)
        return 3

    for role, text in (("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")):
        await store.append_turn(thread_id="thr-1", role=role, content=text)

    service = SessionTimelineService(
        dialog_turn_store=store,
        mcp_tool_call_repository=_McpRepo(),  # type: ignore[arg-type]
        clear_checkpoints=clear_checkpoints,
    )
    deleted = await service.truncate_dialog_turns(thread_id="thr-1", keep=2)
    assert deleted == 2
    assert cleared == ["thr-1"]
    remaining = await service.list_dialog_turns(thread_id="thr-1", limit=10)
    assert [turn.content for turn in remaining] == ["q1", "a1"]
