# src/palatium_ai/infrastructure/retention/session_handler.py

"""Purge inactive sessions and their dialog_turns (no RLS on these tables)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from palatium_ai.domain.policies.retention import RetentionPolicy, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassReport
from palatium_ai.infrastructure.database.models.dialog_turn import DialogTurnORM
from palatium_ai.infrastructure.database.models.session import SessionORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SessionTranscriptRetentionHandler:
    """session_transcript: delete turns then sessions past inactivity window."""

    retention_class = "session_transcript"

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
            thread_ids = await self._candidate_thread_ids(session, cutoff=cutoff, limit=limit)
        decision = RetentionPolicy.decide("session_transcript")
        return RetentionClassReport(
            retention_class="session_transcript",
            action=decision.action,
            candidates=len(thread_ids),
            detail=f"cutoff={cutoff.isoformat()};batch_cap={limit}",
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        cutoff = self._cutoff()
        async with self._session_factory() as session:
            thread_ids = await self._candidate_thread_ids(session, cutoff=cutoff, limit=limit)
            if not thread_ids:
                await session.commit()
                return RetentionClassReport(
                    retention_class="session_transcript",
                    action="delete",
                    candidates=0,
                    acted=0,
                    detail=f"cutoff={cutoff.isoformat()}",
                )
            turns = await session.execute(delete(DialogTurnORM).where(DialogTurnORM.thread_id.in_(thread_ids)))
            sessions = await session.execute(delete(SessionORM).where(SessionORM.thread_id.in_(thread_ids)))
            await session.commit()
            acted = int(getattr(sessions, "rowcount", 0) or 0)
            turn_rows = int(getattr(turns, "rowcount", 0) or 0)
        return RetentionClassReport(
            retention_class="session_transcript",
            action="delete",
            candidates=len(thread_ids),
            acted=acted,
            detail=f"sessions={acted};turns={turn_rows};cutoff={cutoff.isoformat()}",
        )

    def _cutoff(self) -> datetime:
        return RetentionPolicy.session_inactivity_cutoff(now=datetime.now(UTC), windows=self._windows)

    async def _candidate_thread_ids(
        self,
        session: AsyncSession,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[str]:
        batch = max(1, min(limit, self._windows.batch_size))
        result = await session.execute(
            select(SessionORM.thread_id)
            .where(SessionORM.updated_at < cutoff)
            .order_by(SessionORM.updated_at.asc())
            .limit(batch)
        )
        return [str(row) for row in result.scalars().all()]
