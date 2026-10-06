# src/palatium_ai/infrastructure/retention/checkpointer_handler.py

"""Purge LangGraph Postgres checkpoints aligned with session inactivity (ADR 0002)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from palatium_ai.domain.policies.retention import RetentionClass, RetentionPolicy, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassReport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_CHECKPOINT_TABLES: tuple[str, ...] = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
_DELETE_BY_CONVERSATION: dict[str, str] = {
    "checkpoint_writes": (
        "DELETE FROM public.checkpoint_writes AS c WHERE c.thread_id = :conv_id OR starts_with(c.thread_id, :prefix)"
    ),
    "checkpoint_blobs": (
        "DELETE FROM public.checkpoint_blobs AS c WHERE c.thread_id = :conv_id OR starts_with(c.thread_id, :prefix)"
    ),
    "checkpoints": (
        "DELETE FROM public.checkpoints AS c WHERE c.thread_id = :conv_id OR starts_with(c.thread_id, :prefix)"
    ),
}
_DELETE_BY_THREAD: dict[str, str] = {
    "checkpoint_writes": "DELETE FROM public.checkpoint_writes WHERE thread_id = :tid",
    "checkpoint_blobs": "DELETE FROM public.checkpoint_blobs WHERE thread_id = :tid",
    "checkpoints": "DELETE FROM public.checkpoints WHERE thread_id = :tid",
}


class CheckpointerRetentionHandler:
    """checkpointer: drop LG rows for inactive sessions and orphan thread keys."""

    retention_class: RetentionClass = "checkpointer"

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
            if not await self._tables_ready(session):
                return RetentionClassReport(
                    retention_class="checkpointer",
                    action="delete",
                    candidates=0,
                    detail="tables_absent",
                )
            inactive = await self._inactive_conversation_ids(session, cutoff=cutoff, limit=limit)
            orphans = await self._orphan_checkpoint_thread_ids(session, limit=limit)
        decision = RetentionPolicy.decide("checkpointer")
        return RetentionClassReport(
            retention_class="checkpointer",
            action=decision.action,
            candidates=len(inactive) + len(orphans),
            detail=(f"cutoff={cutoff.isoformat()};inactive={len(inactive)};orphans={len(orphans)};batch_cap={limit}"),
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        cutoff = self._cutoff()
        async with self._session_factory() as session:
            if not await self._tables_ready(session):
                await session.commit()
                return RetentionClassReport(
                    retention_class="checkpointer",
                    action="delete",
                    candidates=0,
                    acted=0,
                    detail="tables_absent",
                )
            inactive = await self._inactive_conversation_ids(session, cutoff=cutoff, limit=limit)
            orphans = await self._orphan_checkpoint_thread_ids(session, limit=limit)
            deleted_conv = await self._delete_for_conversations(session, inactive)
            deleted_orphan = await self._delete_exact_thread_ids(session, orphans)
            await session.commit()
        acted = deleted_conv + deleted_orphan
        return RetentionClassReport(
            retention_class="checkpointer",
            action="delete",
            candidates=len(inactive) + len(orphans),
            acted=acted,
            detail=(
                f"cutoff={cutoff.isoformat()};inactive_threads={len(inactive)};"
                f"orphan_keys={len(orphans)};checkpoint_rows={acted}"
            ),
        )

    def _cutoff(self) -> datetime:
        return RetentionPolicy.checkpoint_inactivity_cutoff(
            now=datetime.now(UTC),
            windows=self._windows,
        )

    async def _tables_ready(self, session: AsyncSession) -> bool:
        result = await session.execute(text("SELECT to_regclass('public.checkpoints') IS NOT NULL"))
        return bool(result.scalar())

    async def _inactive_conversation_ids(
        self,
        session: AsyncSession,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[str]:
        batch = max(1, min(limit, self._windows.batch_size))
        result = await session.execute(
            text(
                """
                SELECT thread_id
                FROM palatium_ai.sessions
                WHERE updated_at < :cutoff
                ORDER BY updated_at ASC
                LIMIT :lim
                """
            ),
            {"cutoff": cutoff, "lim": batch},
        )
        return [str(row[0]) for row in result.all()]

    async def _orphan_checkpoint_thread_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        batch = max(1, min(limit, self._windows.batch_size))
        result = await session.execute(
            text(
                """
                SELECT c.thread_id
                FROM public.checkpoints AS c
                WHERE NOT EXISTS (
                  SELECT 1
                  FROM palatium_ai.sessions AS s
                  WHERE c.thread_id = s.thread_id
                     OR starts_with(c.thread_id, s.thread_id || ':')
                )
                GROUP BY c.thread_id
                ORDER BY min(c.checkpoint_id) ASC
                LIMIT :lim
                """
            ),
            {"lim": batch},
        )
        return [str(row[0]) for row in result.all()]

    async def _delete_for_conversations(self, session: AsyncSession, conversation_ids: list[str]) -> int:
        if not conversation_ids:
            return 0
        total = 0
        for conv_id in conversation_ids:
            for table in _CHECKPOINT_TABLES:
                # Table names are a closed allowlist (_CHECKPOINT_TABLES), not user input.
                result = await session.execute(
                    text(_DELETE_BY_CONVERSATION[table]),
                    {"conv_id": conv_id, "prefix": f"{conv_id}:"},
                )
                total += int(getattr(result, "rowcount", 0) or 0)
        return total

    async def _delete_exact_thread_ids(self, session: AsyncSession, thread_ids: list[str]) -> int:
        if not thread_ids:
            return 0
        total = 0
        for thread_id in thread_ids:
            for table in _CHECKPOINT_TABLES:
                result = await session.execute(
                    text(_DELETE_BY_THREAD[table]),
                    {"tid": thread_id},
                )
                total += int(getattr(result, "rowcount", 0) or 0)
        return total
