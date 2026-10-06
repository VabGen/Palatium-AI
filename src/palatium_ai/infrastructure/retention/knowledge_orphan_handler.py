# src/palatium_ai/infrastructure/retention/knowledge_orphan_handler.py

"""Delete knowledge documents whose attachment parent is gone (W3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from palatium_ai.domain.policies.retention import RetentionPolicy, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassReport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class KnowledgeOrphanRetentionHandler:
    """knowledge_orphan: documents with no matching attachment past grace window."""

    retention_class = "knowledge_orphan"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        windows: RetentionWindows,
    ) -> None:
        self._session_factory = session_factory
        self._windows = windows

    async def plan(self, *, limit: int) -> RetentionClassReport:
        cutoff = self._cutoff()
        async with self._session_factory() as session:
            candidates = await self._count(session, cutoff=cutoff)
        decision = RetentionPolicy.decide("knowledge_orphan")
        return RetentionClassReport(
            retention_class="knowledge_orphan",
            action=decision.action,
            candidates=candidates,
            detail=f"cutoff={cutoff.isoformat()};batch_cap={limit}",
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        cutoff = self._cutoff()
        batch = max(1, min(limit, self._windows.batch_size))
        async with self._session_factory() as session:
            deleted = await self._delete(session, cutoff=cutoff, limit=batch)
            await session.commit()
        return RetentionClassReport(
            retention_class="knowledge_orphan",
            action="delete",
            candidates=deleted,
            acted=deleted,
            detail=f"cutoff={cutoff.isoformat()}",
        )

    def _cutoff(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self._windows.knowledge_orphan_days)

    async def _count(self, session: AsyncSession, *, cutoff: datetime) -> int:
        result = await session.execute(
            text("SELECT knowledge.retention_count_orphans(:cutoff)"),
            {"cutoff": cutoff},
        )
        return int(result.scalar_one() or 0)

    async def _delete(self, session: AsyncSession, *, cutoff: datetime, limit: int) -> int:
        result = await session.execute(
            text("SELECT knowledge.retention_delete_orphans(:cutoff, :lim)"),
            {"cutoff": cutoff, "lim": limit},
        )
        return int(result.scalar_one() or 0)
