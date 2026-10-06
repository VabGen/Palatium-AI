# tests/unit/test_session_retention_handler.py

"""Session transcript retention unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from palatium_ai.domain.policies.retention import RetentionPolicy, RetentionWindows
from palatium_ai.infrastructure.retention.session_handler import SessionTranscriptRetentionHandler

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_session_inactivity_cutoff() -> None:
    windows = RetentionWindows(session_days=30)
    cutoff = RetentionPolicy.session_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(days=30)


@pytest.mark.asyncio()
async def test_session_handler_plan_counts_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = SessionTranscriptRetentionHandler(MagicMock(), windows=RetentionWindows(session_days=30))

    async def _fake_ids(session: object, *, cutoff: datetime, limit: int) -> list[str]:
        assert limit == 10
        assert cutoff.tzinfo is not None
        return ["t1", "t2"]

    monkeypatch.setattr(handler, "_candidate_thread_ids", _fake_ids)
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.plan(limit=10)
    assert report.retention_class == "session_transcript"
    assert report.candidates == 2
    assert report.action == "delete"


@pytest.mark.asyncio()
async def test_memory_handler_rejects_unknown_class() -> None:
    from palatium_ai.infrastructure.retention.memory_handler import MemoryRetentionHandler

    with pytest.raises(ValueError, match="unsupported"):
        MemoryRetentionHandler(
            MagicMock(),
            retention_class="session_transcript",  # type: ignore[arg-type]
            windows=RetentionWindows(),
        )


@pytest.mark.asyncio()
async def test_session_handler_execute_deletes_turns_then_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = SessionTranscriptRetentionHandler(MagicMock(), windows=RetentionWindows(session_days=30))

    async def _fake_ids(session: object, *, cutoff: datetime, limit: int) -> list[str]:
        return ["thread-a"]

    monkeypatch.setattr(handler, "_candidate_thread_ids", _fake_ids)
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(rowcount=4),
            SimpleNamespace(rowcount=1),
        ]
    )
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.execute(limit=50)
    assert report.acted == 1
    assert "turns=4" in report.detail
    assert session.execute.await_count == 2
    session.commit.assert_awaited()
