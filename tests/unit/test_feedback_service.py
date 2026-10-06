# tests/unit/test_feedback_service.py

"""Feedback persistence use-case unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from palatium_ai.application.services.feedback_service import FeedbackService
from palatium_ai.domain.feedback.models import FeedbackUpsertResult, MessageFeedback


@pytest.mark.asyncio()
async def test_submit_like_stores() -> None:
    repo = AsyncMock()
    stored = MessageFeedback(
        id=uuid4(),
        user_id="u1",
        message_id="m1",
        rating="like",
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
        updated_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    repo.upsert = AsyncMock(return_value=FeedbackUpsertResult(status="stored", feedback=stored))
    service = FeedbackService(repo)

    result = await service.submit(user_id="u1", message_id="m1", action="like", thread_id="t1")
    assert result.status == "stored"
    assert result.feedback is not None
    assert result.feedback.rating == "like"
    repo.upsert.assert_awaited_once()


@pytest.mark.asyncio()
async def test_submit_clear_deletes() -> None:
    repo = AsyncMock()
    repo.clear = AsyncMock(return_value=FeedbackUpsertResult(status="cleared", feedback=None))
    service = FeedbackService(repo)

    result = await service.submit(user_id="u1", message_id="m1", action="clear")
    assert result.status == "cleared"
    repo.clear.assert_awaited_once()
    repo.upsert.assert_not_called()
