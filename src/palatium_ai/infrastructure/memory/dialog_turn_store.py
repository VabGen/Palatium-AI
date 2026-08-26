# src/palatium_ai/infrastructure/memory/dialog_turn_store.py

"""Postgres-backed DialogTurnStore."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select

from palatium_ai.domain.memory.turns import DialogRole, DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.database.models.dialog_turn import DialogTurnORM
from palatium_ai.infrastructure.database.models.session import SessionORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresDialogTurnStore:
    """Implements DialogTurnStore against palatium_ai.dialog_turns."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: DialogRole,
        content: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DialogTurn:
        """Append one turn; returns persisted turn with seq."""
        async with self._session_factory() as session:
            session_id = await self._resolve_session_id(session, thread_id=thread_id)
            next_seq = await self._next_seq(session, thread_id=thread_id)
            entity = DialogTurnORM(
                session_id=session_id,
                thread_id=thread_id,
                role=role,
                content=content,
                payload=payload,
                task_id=task_id,
                seq=next_seq,
            )
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return _to_domain(entity)

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        """Load last-K turns for a thread (oldest → newest)."""
        safe_limit = max(1, min(limit, 50))
        async with self._session_factory() as session:
            result = await session.execute(
                select(DialogTurnORM)
                .where(DialogTurnORM.thread_id == thread_id)
                .order_by(DialogTurnORM.seq.desc())
                .limit(safe_limit)
            )
            rows = list(result.scalars().all())
            rows.reverse()
            return DialogTurnWindow(
                thread_id=thread_id,
                turns=tuple(_to_domain(row) for row in rows),
                limit=safe_limit,
            )

    async def _resolve_session_id(self, session: AsyncSession, *, thread_id: str) -> object | None:
        result = await session.execute(select(SessionORM.id).where(SessionORM.thread_id == thread_id))
        return result.scalar_one_or_none()

    async def _next_seq(self, session: AsyncSession, *, thread_id: str) -> int:
        result = await session.execute(
            select(func.coalesce(func.max(DialogTurnORM.seq), -1)).where(DialogTurnORM.thread_id == thread_id)
        )
        current = result.scalar_one()
        return int(current) + 1


def _to_domain(entity: DialogTurnORM) -> DialogTurn:
    return DialogTurn(
        id=entity.id,
        thread_id=entity.thread_id,
        role=cast("DialogRole", entity.role),
        content=entity.content,
        payload=dict(entity.payload) if entity.payload is not None else None,
        task_id=entity.task_id,
        seq=entity.seq,
        created_at=entity.created_at,
    )
