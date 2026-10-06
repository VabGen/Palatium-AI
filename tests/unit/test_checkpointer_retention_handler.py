# tests/unit/test_checkpointer_retention_handler.py

"""Checkpointer retention unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from palatium_ai.domain.policies.retention import RetentionPolicy, RetentionWindows
from palatium_ai.infrastructure.retention.checkpointer_handler import CheckpointerRetentionHandler

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_checkpoint_inactivity_cutoff() -> None:
    windows = RetentionWindows(checkpoint_days=30)
    cutoff = RetentionPolicy.checkpoint_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(days=30)


@pytest.mark.asyncio()
async def test_checkpointer_plan_tables_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = CheckpointerRetentionHandler(MagicMock(), windows=RetentionWindows())

    async def _absent(session: object) -> bool:
        return False

    monkeypatch.setattr(handler, "_tables_ready", _absent)
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.plan(limit=10)
    assert report.candidates == 0
    assert report.detail == "tables_absent"


@pytest.mark.asyncio()
async def test_checkpointer_execute_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = CheckpointerRetentionHandler(MagicMock(), windows=RetentionWindows(checkpoint_days=30))

    async def _ready(session: object) -> bool:
        return True

    async def _inactive(session: object, *, cutoff: datetime, limit: int) -> list[str]:
        return ["conv-1"]

    async def _orphans(session: object, *, limit: int) -> list[str]:
        return ["orphan:task"]

    async def _del_conv(session: object, ids: list[str]) -> int:
        assert ids == ["conv-1"]
        return 4

    async def _del_exact(session: object, ids: list[str]) -> int:
        assert ids == ["orphan:task"]
        return 2

    monkeypatch.setattr(handler, "_tables_ready", _ready)
    monkeypatch.setattr(handler, "_inactive_conversation_ids", _inactive)
    monkeypatch.setattr(handler, "_orphan_checkpoint_thread_ids", _orphans)
    monkeypatch.setattr(handler, "_delete_for_conversations", _del_conv)
    monkeypatch.setattr(handler, "_delete_exact_thread_ids", _del_exact)

    session = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.execute(limit=50)
    assert report.candidates == 2
    assert report.acted == 6
    session.commit.assert_awaited()
