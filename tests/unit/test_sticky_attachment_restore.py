# tests/unit/test_sticky_attachment_restore.py

"""Follow-up turns restore sticky pending_attachment_ids after composer clears chips."""

from __future__ import annotations

from uuid import UUID

import pytest

from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.application.services.intent_turn_helpers import (
    PENDING_ATTACHMENT_IDS_KEY,
    serialize_pending_attachment_ids,
)

_ID_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ID_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class _Session:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context


class _SessionService:
    def __init__(self, pending: list[UUID] | None = None) -> None:
        ctx: dict[str, object] = {}
        if pending:
            ctx[PENDING_ATTACHMENT_IDS_KEY] = serialize_pending_attachment_ids(pending)
        self._session = _Session(ctx)

    async def get_session(self, *, thread_id: str) -> _Session:
        return self._session


@pytest.mark.asyncio()
async def test_resolve_restores_pending_when_no_explicit_ids() -> None:
    service = IntentService.__new__(IntentService)
    service._session_service = _SessionService(pending=[_ID_A, _ID_B])  # type: ignore[attr-defined]
    resolved = await service._resolve_turn_attachment_ids(  # type: ignore[attr-defined]
        None,
        thread_id="thread-1",
        restore_pending=True,
    )
    assert resolved == [_ID_A, _ID_B]


@pytest.mark.asyncio()
async def test_explicit_ids_win_over_pending() -> None:
    service = IntentService.__new__(IntentService)
    service._session_service = _SessionService(pending=[_ID_A])  # type: ignore[attr-defined]
    resolved = await service._resolve_turn_attachment_ids(  # type: ignore[attr-defined]
        [_ID_B],
        thread_id="thread-1",
        restore_pending=True,
    )
    assert resolved == [_ID_B]


@pytest.mark.asyncio()
async def test_no_restore_without_flag() -> None:
    service = IntentService.__new__(IntentService)
    service._session_service = _SessionService(pending=[_ID_A])  # type: ignore[attr-defined]
    resolved = await service._resolve_turn_attachment_ids(  # type: ignore[attr-defined]
        None,
        thread_id="thread-1",
        restore_pending=False,
    )
    assert resolved is None
