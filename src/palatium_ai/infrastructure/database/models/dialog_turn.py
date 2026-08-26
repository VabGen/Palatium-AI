# src/palatium_ai/infrastructure/database/models/dialog_turn.py

"""Dialog turn ORM (transcript)."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class DialogTurnORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ordered conversation turn persisted per thread."""

    __tablename__ = "dialog_turns"
    __table_args__ = (
        Index("ix_dialog_turns_thread_seq", "thread_id", "seq"),
        Index("ix_dialog_turns_thread_created", "thread_id", "created_at"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    session_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid,
        ForeignKey(f"{DEFAULT_DB_SCHEMA}.sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
