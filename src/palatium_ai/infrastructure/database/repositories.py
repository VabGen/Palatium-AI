# src/palatium_ai/infrastructure/database/repositories.py

"""SQLAlchemy repositories for persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select, update

from palatium_ai.domain.sessions.ownership import next_session_owner
from palatium_ai.infrastructure.database.models import McpToolCallORM, SessionORM

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SessionRepository:
    """Persistence operations for `SessionORM`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def touch_session(
        self,
        *,
        thread_id: str,
        user_id: str | None = None,
        title: str | None = None,
        context_patch: dict[str, Any] | None = None,
        status: str = "active",
    ) -> SessionORM:
        """Create or update a session identified by `thread_id`."""
        async with self._session_factory() as session:
            existing = await self.get_by_thread_id(thread_id=thread_id, session=session)
            if existing is None:
                entity = SessionORM(
                    thread_id=thread_id,
                    user_id=user_id,
                    title=title,
                    status=status,
                    context=context_patch or {},
                )
                session.add(entity)
            else:
                entity = existing
                entity.status = status
                entity.user_id = next_session_owner(
                    existing_owner=entity.user_id,
                    incoming_user_id=user_id,
                )
                if title is not None and not entity.title:
                    entity.title = title
                if context_patch:
                    entity.context = {**entity.context, **context_patch}

            await session.commit()
            await session.refresh(entity)
            return entity

    async def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[SessionORM]:
        """Return the most recently updated sessions (optionally scoped to one user)."""
        async with self._session_factory() as session:
            stmt = select(SessionORM).order_by(SessionORM.updated_at.desc()).offset(offset).limit(limit)
            if user_id is not None:
                stmt = stmt.where(SessionORM.user_id == user_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_by_thread_id(
        self,
        *,
        thread_id: str,
        session: AsyncSession | None = None,
    ) -> SessionORM | None:
        """Find a session by its stable thread identifier."""
        if session is not None:
            result = await session.execute(select(SessionORM).where(SessionORM.thread_id == thread_id))
            return result.scalar_one_or_none()

        async with self._session_factory() as owned_session:
            result = await owned_session.execute(select(SessionORM).where(SessionORM.thread_id == thread_id))
            return result.scalar_one_or_none()


class McpToolCallRepository:
    """Persistence operations for `McpToolCallORM`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_call(
        self,
        *,
        conversation_id: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
        content: list[dict[str, object]],
        is_error: bool,
        event: str,
        user_id: str | None = None,
    ) -> McpToolCallORM:
        """Persist a single MCP tool call and link it to a known session when possible."""
        async with self._session_factory() as session:
            session_id = await self._resolve_session_id(session=session, thread_id=conversation_id)
            entity = McpToolCallORM(
                conversation_id=conversation_id,
                session_id=session_id,
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
                content=content,
                is_error=is_error,
                event=event,
                user_id=user_id,
            )
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return entity

    async def list_by_thread_id(
        self,
        *,
        thread_id: str,
        limit: int = 100,
        offset: int = 0,
        event: str | None = None,
        is_error: bool | None = None,
        server_name: str | None = None,
        include_archived: bool = False,
    ) -> list[McpToolCallORM]:
        """Return MCP tool calls linked to a session or matching its conversation ID."""
        async with self._session_factory() as session:
            session_id = await self._resolve_session_id(session=session, thread_id=thread_id)
            filters = [McpToolCallORM.conversation_id == thread_id]
            if session_id is not None:
                filters.append(McpToolCallORM.session_id == session_id)

            query = select(McpToolCallORM).where(or_(*filters))
            if event is not None:
                query = query.where(McpToolCallORM.event == event)
            if is_error is not None:
                query = query.where(McpToolCallORM.is_error == is_error)
            if server_name is not None:
                query = query.where(McpToolCallORM.server_name == server_name)
            if not include_archived:
                query = query.where(McpToolCallORM.archived_at.is_(None))

            result = await session.execute(query.order_by(McpToolCallORM.created_at.desc()).offset(offset).limit(limit))
            return list(result.scalars().all())

    async def purge_archived_older_than(
        self,
        *,
        older_than: datetime,
        dry_run: bool = True,
        batch_size: int | None = None,
    ) -> int:
        """
        Physically delete archived MCP tool calls older than the given cutoff.

        By default this method performs a dry-run and only returns the number
        of candidate rows. Set `dry_run=False` to execute the delete.
        """
        async with self._session_factory() as session:
            candidate_query = (
                select(McpToolCallORM.id)
                .where(McpToolCallORM.archived_at.is_not(None))
                .where(McpToolCallORM.archived_at < older_than)
                .order_by(McpToolCallORM.archived_at.asc())
            )
            if batch_size is not None:
                candidate_query = candidate_query.limit(batch_size)

            candidate_ids = list((await session.execute(candidate_query)).scalars().all())
            if dry_run or not candidate_ids:
                return len(candidate_ids)

            await session.execute(delete(McpToolCallORM).where(McpToolCallORM.id.in_(candidate_ids)))
            await session.commit()
            return len(candidate_ids)

    async def archive_older_than(
        self,
        *,
        older_than: datetime,
        dry_run: bool = True,
        batch_size: int | None = None,
        event: str | None = None,
        is_error: bool | None = None,
        server_name: str | None = None,
    ) -> int:
        """
        Soft-archive MCP tool calls older than the given cutoff.

        Only non-archived rows are considered. By default this method performs
        a dry-run and only returns the number of candidate rows.
        """
        async with self._session_factory() as session:
            candidate_query = (
                select(McpToolCallORM.id)
                .where(McpToolCallORM.archived_at.is_(None))
                .where(McpToolCallORM.created_at < older_than)
                .order_by(McpToolCallORM.created_at.asc())
            )
            if event is not None:
                candidate_query = candidate_query.where(McpToolCallORM.event == event)
            if is_error is not None:
                candidate_query = candidate_query.where(McpToolCallORM.is_error == is_error)
            if server_name is not None:
                candidate_query = candidate_query.where(McpToolCallORM.server_name == server_name)
            if batch_size is not None:
                candidate_query = candidate_query.limit(batch_size)

            candidate_ids = list((await session.execute(candidate_query)).scalars().all())
            if dry_run or not candidate_ids:
                return len(candidate_ids)

            await session.execute(
                update(McpToolCallORM).where(McpToolCallORM.id.in_(candidate_ids)).values(archived_at=datetime.now(UTC))
            )
            await session.commit()
            return len(candidate_ids)

    async def retention_report(self, *, purge_older_than: datetime) -> dict[str, int]:
        """Return retention counters for active, archived, and purge-eligible rows."""
        async with self._session_factory() as session:
            active = await session.scalar(
                select(func.count()).select_from(McpToolCallORM).where(McpToolCallORM.archived_at.is_(None))
            )
            archived = await session.scalar(
                select(func.count()).select_from(McpToolCallORM).where(McpToolCallORM.archived_at.is_not(None))
            )
            purge_candidates = await session.scalar(
                select(func.count())
                .select_from(McpToolCallORM)
                .where(McpToolCallORM.archived_at.is_not(None))
                .where(McpToolCallORM.archived_at < purge_older_than)
            )

            return {
                "active": int(active or 0),
                "archived": int(archived or 0),
                "purge_candidates": int(purge_candidates or 0),
            }

    async def _resolve_session_id(
        self,
        *,
        session: AsyncSession,
        thread_id: str,
    ) -> UUID | None:
        """Resolve optional `SessionORM.id` by thread ID for hard-link persistence."""
        result = await session.execute(select(SessionORM.id).where(SessionORM.thread_id == thread_id))
        return result.scalar_one_or_none()
