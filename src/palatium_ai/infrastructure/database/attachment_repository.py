# src/palatium_ai/infrastructure/database/attachment_repository.py

"""Postgres AttachmentRepositoryPort.

Two independent isolation mechanisms are applied on purpose (060):

* every statement carries an explicit ``user_id`` predicate, so a logic error
  cannot widen a result set; and
* :func:`set_rls_user_scope` binds ``palatium.user_id`` in the same transaction,
  because the ``attachments`` table uses ``FORCE ROW LEVEL SECURITY`` — without
  the binding the policy predicate is false and the statement sees no rows at all.

The second point is not defence in depth but a hard requirement: forgetting the
binding yields empty results, not leaked ones, so a missed call surfaces as a
failing test rather than a silent cross-tenant read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import delete, func, select, update

from palatium_ai.domain.attachments import Attachment
from palatium_ai.domain.attachments.types import (
    AttachmentMode,
    AttachmentRejectionReason,
    AttachmentStatus,
)
from palatium_ai.infrastructure.database.models import AttachmentORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _attachment_from_orm(entity: AttachmentORM) -> Attachment:
    """Map a row to the domain aggregate.

    ``mode``/``status``/``rejection_reason`` are cast rather than re-validated:
    the values were validated by the aggregate before the insert, and raising on
    read would turn DB drift into an outage instead of a visible bad row.
    """
    return Attachment(
        id=entity.id,
        user_id=entity.user_id,
        thread_id=entity.thread_id,
        filename=entity.filename,
        mime_type=entity.mime_type,
        size_bytes=entity.size_bytes,
        blob_key=entity.blob_key,
        mode=cast("AttachmentMode", entity.mode),
        status=cast("AttachmentStatus", entity.status),
        page_count=entity.page_count,
        derived_text_key=entity.derived_text_key,
        rejection_reason=cast("AttachmentRejectionReason | None", entity.rejection_reason),
        error=entity.error,
        created_at=entity.created_at,
        expires_at=entity.expires_at,
    )


class PostgresAttachmentRepository:
    """SQLAlchemy adapter implementing ``AttachmentRepositoryPort``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, attachment: Attachment) -> Attachment:
        """Insert a new attachment row."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, attachment.user_id)
            entity = AttachmentORM(
                id=attachment.id,
                user_id=attachment.user_id,
                thread_id=attachment.thread_id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
                blob_key=attachment.blob_key,
                mode=attachment.mode,
                status=attachment.status,
                page_count=attachment.page_count,
                derived_text_key=attachment.derived_text_key,
                rejection_reason=attachment.rejection_reason,
                error=attachment.error,
                created_at=attachment.created_at,
                expires_at=attachment.expires_at,
            )
            session.add(entity)
            # Refresh *before* the commit: ``set_rls_user_scope`` binds
            # ``palatium.user_id`` with ``set_config(..., is_local=true)``, so the
            # binding dies with the transaction. A reload after ``commit()`` would
            # run in a new transaction without the scope, the FORCE RLS predicate
            # would be false, and the insert path would fail on the read-back.
            await session.flush()
            await session.refresh(entity)
            await session.commit()
            return _attachment_from_orm(entity)

    async def save(self, attachment: Attachment) -> Attachment:
        """Persist the full aggregate; a row outside ``user_id`` is a hard error."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, attachment.user_id)
            stmt = (
                update(AttachmentORM)
                .where(AttachmentORM.id == attachment.id, AttachmentORM.user_id == attachment.user_id)
                .values(
                    thread_id=attachment.thread_id,
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    size_bytes=attachment.size_bytes,
                    blob_key=attachment.blob_key,
                    mode=attachment.mode,
                    status=attachment.status,
                    page_count=attachment.page_count,
                    derived_text_key=attachment.derived_text_key,
                    rejection_reason=attachment.rejection_reason,
                    error=attachment.error,
                    expires_at=attachment.expires_at,
                )
                .returning(AttachmentORM)
            )
            result = await session.execute(stmt)
            entity = result.scalar_one_or_none()
            await session.commit()
            if entity is None:
                # No user id in the message: it is an owner identity and this
                # exception may end up in a log or an audit event (060).
                msg = f"attachment {attachment.id} not found for the acting user"
                raise LookupError(msg)
            return _attachment_from_orm(entity)

    async def get(self, attachment_id: UUID, *, user_id: str) -> Attachment | None:
        """Fetch one attachment owned by ``user_id``."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            entity = await self._get_orm(session, attachment_id, user_id)
            return _attachment_from_orm(entity) if entity is not None else None

    async def get_many(self, attachment_ids: Sequence[UUID], *, user_id: str) -> list[Attachment]:
        """Fetch several attachments, skipping ids not owned by ``user_id``."""
        if not attachment_ids:
            return []
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(AttachmentORM)
                .where(AttachmentORM.id.in_(list(attachment_ids)), AttachmentORM.user_id == user_id)
                .order_by(AttachmentORM.created_at.asc())
            )
            return [_attachment_from_orm(row) for row in result.scalars().all()]

    async def list_for_thread(self, thread_id: str, *, user_id: str) -> list[Attachment]:
        """List attachments bound to one thread, newest first."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(AttachmentORM)
                .where(AttachmentORM.thread_id == thread_id, AttachmentORM.user_id == user_id)
                .order_by(AttachmentORM.created_at.desc())
            )
            return [_attachment_from_orm(row) for row in result.scalars().all()]

    async def count_for_thread(self, thread_id: str, *, user_id: str) -> int:
        """Count attachments in a thread to enforce the per-turn intake limit."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(func.count())
                .select_from(AttachmentORM)
                .where(AttachmentORM.thread_id == thread_id, AttachmentORM.user_id == user_id)
            )
            return int(result.scalar_one())

    async def delete(self, attachment_id: UUID, *, user_id: str) -> None:
        """Remove an attachment row owned by ``user_id``; a missing row is not an error."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            await session.execute(
                delete(AttachmentORM).where(
                    AttachmentORM.id == attachment_id,
                    AttachmentORM.user_id == user_id,
                )
            )
            await session.commit()

    async def list_expired(
        self,
        cutoff: datetime,
        *,
        user_id: str,
        limit: int,
    ) -> list[Attachment]:
        """Oldest-first expired rows for one owner; see the port docstring (060)."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(AttachmentORM)
                .where(
                    AttachmentORM.user_id == user_id,
                    AttachmentORM.expires_at.is_not(None),
                    AttachmentORM.expires_at <= cutoff,
                )
                .order_by(AttachmentORM.expires_at.asc())
                .limit(limit)
            )
            return [_attachment_from_orm(row) for row in result.scalars().all()]

    @staticmethod
    async def _get_orm(session: AsyncSession, attachment_id: UUID, user_id: str) -> AttachmentORM | None:
        result = await session.execute(
            select(AttachmentORM).where(
                AttachmentORM.id == attachment_id,
                AttachmentORM.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
