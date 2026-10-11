"""Sticky pending_attachment_ids: SB1 no blind restore; explicit uploads still win."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from palatium_ai.application.services.intent_hitl_flow import IntentHitlFlow
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.application.services.intent_turn_helpers import (
    PENDING_ATTACHMENT_IDS_KEY,
    serialize_pending_attachment_ids,
)
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption

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
        self.patches: list[dict[str, object]] = []

    async def get_session(self, *, thread_id: str) -> _Session:
        return self._session

    async def touch_session(self, **kwargs: object) -> None:
        patch = kwargs.get("context_patch")
        if isinstance(patch, dict):
            self.patches.append(patch)
            self._session.context.update(patch)


@pytest.mark.asyncio()
async def test_resolve_skips_sticky_pending_when_no_explicit_ids() -> None:
    """SB1: session pending is kept for SB2 rehydrate, not auto-fenced."""
    service = IntentService.__new__(IntentService)
    service._session_service = _SessionService(pending=[_ID_A, _ID_B])  # type: ignore[attr-defined]
    resolved = await service._resolve_turn_attachment_ids(  # type: ignore[attr-defined]
        None,
        thread_id="thread-1",
        restore_pending=True,
    )
    assert resolved is None


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


@pytest.mark.asyncio()
async def test_hitl_choice_resume_does_not_pass_pending_as_explicit() -> None:
    """HITL resume keeps sticky in session for SB2; never fences as explicit_upload."""
    process_turn = AsyncMock(return_value=object())

    class _SessionsWithAccess(_SessionService):
        async def assert_thread_access(self, **_kwargs: object) -> None:
            return None

    sessions = _SessionsWithAccess(pending=[_ID_A])
    flow = IntentHitlFlow(
        graph_runner=AsyncMock(),  # type: ignore[arg-type]
        session_service=sessions,  # type: ignore[arg-type]
        hitl_service=AsyncMock(),  # type: ignore[arg-type]
        kill_switch=AsyncMock(),  # type: ignore[arg-type]
        cost_budget=AsyncMock(),  # type: ignore[arg-type]
        process_turn=process_turn,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    card = HITLCardView(
        card_id="card-1",
        thread_id="thread-1",
        task_id="task-1",
        purpose="user_choice",
        title="Pick",
        options=(
            HITLOption(
                action_id="topic_travel",
                label="путешествия",
                kind="custom",
                style="primary",
                action_token="tok",
            ),
        ),
        risk_score=0.2,
        status="pending",
        created_at=now,
        expires_at=now,
    )
    await flow.process_hitl_choice(
        thread_id="thread-1",
        action_id="topic_travel",
        card=card,
        user_id="user-1",
    )
    process_turn.assert_awaited_once()
    kwargs = process_turn.await_args.kwargs
    assert kwargs["attachment_ids"] is None
    assert PENDING_ATTACHMENT_IDS_KEY in sessions._session.context
