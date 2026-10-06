# src/palatium_ai/infrastructure/database/models/attachment.py

"""Attachment persistence model (metadata only — bytes live in the blob store)."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AttachmentORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One uploaded attachment and its intake/security lifecycle state.

    ``user_id`` is NOT NULL on purpose: the RLS policy compares it to
    ``palatium.user_id``, and a nullable owner would create a row that belongs to
    nobody and therefore cannot be reached or reclaimed (060).
    """

    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("blob_key"),
        Index("ix_attachments_thread_created_at", "thread_id", "created_at"),
        Index("ix_attachments_user_status", "user_id", "status"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    blob_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=sa.text("'pending'"),
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    derived_text_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
