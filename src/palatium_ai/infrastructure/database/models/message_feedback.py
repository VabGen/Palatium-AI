# src/palatium_ai/infrastructure/database/models/message_feedback.py

"""Persisted like/dislike on assistant messages (web-embed §5 п.17)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MessageFeedbackORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rating per (user, message); cleared rows are deleted, not nulled."""

    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id"),
        CheckConstraint("rating IN ('like', 'dislike')", name="ck_message_feedback_rating"),
        Index("ix_message_feedback_thread_created_at", "thread_id", "created_at"),
        Index("ix_message_feedback_user_updated_at", "user_id", "updated_at"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
