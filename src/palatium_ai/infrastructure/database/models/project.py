# src/palatium_ai/infrastructure/database/models/project.py

"""Project persistence model (FORCE RLS by user_id)."""

from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ProjectORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable project folder for pin/history + attachment KB scope id.

    ``user_id`` is NOT NULL: RLS compares it to ``palatium.user_id`` (060).
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_user_updated_at", "user_id", "updated_at"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
