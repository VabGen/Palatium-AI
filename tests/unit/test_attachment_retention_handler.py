# tests/unit/test_attachment_retention_handler.py

"""Global attachment retention handler unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from palatium_ai.domain.policies.retention import RetentionWindows
from palatium_ai.infrastructure.retention.attachment_handler import AttachmentRetentionHandler
from palatium_ai.infrastructure.retention.knowledge_orphan_handler import KnowledgeOrphanRetentionHandler


@pytest.mark.asyncio()
async def test_attachment_handler_rejects_unknown_class() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        AttachmentRetentionHandler(
            MagicMock(),
            retention_class="session_transcript",  # type: ignore[arg-type]
            windows=RetentionWindows(),
            blob_store=MagicMock(),
            pending_ttl_seconds=900,
        )


@pytest.mark.asyncio()
async def test_attachment_handler_plan_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AttachmentRetentionHandler(
        MagicMock(),
        retention_class="attachment_attach",
        windows=RetentionWindows(batch_size=50),
        blob_store=MagicMock(),
        pending_ttl_seconds=900,
        max_chunk_part_index=0,
    )

    async def _count(session: object, *, now: datetime, pending_before: datetime) -> int:
        assert now.tzinfo is not None
        assert pending_before < now
        return 7

    monkeypatch.setattr(handler, "_count", _count)
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.plan(limit=10)
    assert report.candidates == 7
    assert report.action == "delete"
    assert report.retention_class == "attachment_attach"


@pytest.mark.asyncio()
async def test_attachment_handler_execute_purges(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = AsyncMock()
    blob.delete = AsyncMock()
    attachment_id = uuid4()
    handler = AttachmentRetentionHandler(
        MagicMock(),
        retention_class="attachment_index",
        windows=RetentionWindows(batch_size=50),
        blob_store=blob,
        pending_ttl_seconds=900,
        max_chunk_part_index=0,
    )

    async def _list(
        session: object,
        *,
        now: datetime,
        pending_before: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "id": attachment_id,
                "user_id": "u1",
                "blob_key": f"attachments/{attachment_id}",
                "derived_text_key": f"attachments/{attachment_id}.text.json",
                "mode": "index",
                "status": "indexed",
                "project_id": None,
                "contains_pii": False,
                "expires_at": datetime(2026, 1, 1, tzinfo=UTC),
                "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            }
        ]

    async def _purge(row: dict[str, object]) -> int:
        assert row["id"] == attachment_id
        return 2

    monkeypatch.setattr(handler, "_list", _list)
    monkeypatch.setattr(handler, "_purge_one", _purge)
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.execute(limit=10)
    assert report.acted == 1
    assert report.failed == 0
    assert "knowledge_docs=2" in report.detail


@pytest.mark.asyncio()
async def test_knowledge_orphan_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = KnowledgeOrphanRetentionHandler(MagicMock(), windows=RetentionWindows(knowledge_orphan_days=7))

    async def _delete(session: object, *, cutoff: datetime, limit: int) -> int:
        assert limit == 25
        return 3

    monkeypatch.setattr(handler, "_delete", _delete)
    session = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    handler._session_factory = factory

    report = await handler.execute(limit=25)
    assert report.acted == 3
    session.commit.assert_awaited()
