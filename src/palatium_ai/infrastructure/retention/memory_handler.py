# src/palatium_ai/infrastructure/retention/memory_handler.py

"""Global memory.entries retention via SECURITY DEFINER RPCs (RLS-safe)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from palatium_ai.domain.policies.retention import RetentionClass, RetentionPolicy, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassReport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MEMORY_CLASSES: frozenset[str] = frozenset({"memory_medium", "memory_episode", "memory_pii"})


class MemoryRetentionHandler:
    """Backfill NULL expires_at then delete due rows for one memory RetentionClass."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retention_class: RetentionClass,
        windows: RetentionWindows,
    ) -> None:
        if retention_class not in _MEMORY_CLASSES:
            msg = f"unsupported memory retention class: {retention_class}"
            raise ValueError(msg)
        self.retention_class = retention_class
        self._session_factory = session_factory
        self._windows = windows

    async def plan(self, *, limit: int) -> RetentionClassReport:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            candidates = await self._count_expired(session, now=now)
        decision = RetentionPolicy.decide(self.retention_class)
        return RetentionClassReport(
            retention_class=self.retention_class,
            action=decision.action,
            candidates=candidates,
            detail=f"batch_cap={limit}",
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        now = datetime.now(UTC)
        batch = max(1, min(limit, self._windows.batch_size))
        async with self._session_factory() as session:
            backfilled = await self._backfill(session, limit=batch)
            deleted = await self._delete_expired(session, now=now, limit=batch)
            await session.commit()
        return RetentionClassReport(
            retention_class=self.retention_class,
            action="delete",
            candidates=deleted,
            acted=deleted,
            detail=f"backfilled={backfilled};deleted={deleted}",
        )

    async def _count_expired(self, session: AsyncSession, *, now: datetime) -> int:
        result = await session.execute(
            text("SELECT memory.retention_count_expired(:now, :cls)"),
            {"now": now, "cls": self.retention_class},
        )
        return int(result.scalar_one() or 0)

    async def _backfill(self, session: AsyncSession, *, limit: int) -> int:
        result = await session.execute(
            text(
                """
                SELECT memory.retention_backfill_expires(
                  :medium_days, :episode_days, :pii_days, :lim
                )
                """
            ),
            {
                "medium_days": self._windows.memory_medium_days,
                "episode_days": self._windows.memory_episode_days,
                "pii_days": self._windows.memory_pii_days,
                "lim": limit,
            },
        )
        return int(result.scalar_one() or 0)

    async def _delete_expired(self, session: AsyncSession, *, now: datetime, limit: int) -> int:
        result = await session.execute(
            text("SELECT memory.retention_delete_expired(:now, :lim, :cls)"),
            {"now": now, "lim": limit, "cls": self.retention_class},
        )
        return int(result.scalar_one() or 0)
