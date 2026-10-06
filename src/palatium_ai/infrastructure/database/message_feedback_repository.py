# src/palatium_ai/infrastructure/database/message_feedback_repository.py

"""Postgres MessageFeedbackPort with RLS scope (060)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from palatium_ai.domain.feedback.models import FeedbackUpsertResult, MessageFeedback
from palatium_ai.infrastructure.database.models.message_feedback import MessageFeedbackORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.domain.feedback.models import FeedbackRating


def _from_orm(entity: MessageFeedbackORM) -> MessageFeedback:
    return MessageFeedback(
        id=entity.id,
        user_id=entity.user_id,
        message_id=entity.message_id,
        thread_id=entity.thread_id,
        org_id=entity.org_id,
        rating=entity.rating,  # type: ignore[arg-type]
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class PostgresMessageFeedbackRepository:
    """Upsert/clear message feedback under FORCE RLS."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(
        self,
        *,
        user_id: str,
        message_id: str,
        rating: FeedbackRating,
        thread_id: str | None = None,
        org_id: str | None = None,
    ) -> FeedbackUpsertResult:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = (
                insert(MessageFeedbackORM)
                .values(
                    id=uuid4(),
                    user_id=user_id,
                    message_id=message_id,
                    thread_id=thread_id,
                    org_id=org_id,
                    rating=rating,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "message_id"],
                    set_={
                        "rating": rating,
                        "thread_id": thread_id,
                        "org_id": org_id,
                        "updated_at": now,
                    },
                )
                .returning(MessageFeedbackORM)
            )
            result = await session.execute(stmt)
            entity = result.scalar_one()
            await session.commit()
            return FeedbackUpsertResult(status="stored", feedback=_from_orm(entity))

    async def clear(self, *, user_id: str, message_id: str) -> FeedbackUpsertResult:
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            await session.execute(
                delete(MessageFeedbackORM).where(
                    MessageFeedbackORM.user_id == user_id,
                    MessageFeedbackORM.message_id == message_id,
                )
            )
            await session.commit()
            return FeedbackUpsertResult(status="cleared", feedback=None)

    async def get(
        self,
        *,
        user_id: str,
        message_id: str,
    ) -> MessageFeedback | None:
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(MessageFeedbackORM).where(
                    MessageFeedbackORM.user_id == user_id,
                    MessageFeedbackORM.message_id == message_id,
                )
            )
            entity = result.scalar_one_or_none()
            return _from_orm(entity) if entity is not None else None
