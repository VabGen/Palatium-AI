# src/palatium_ai/infrastructure/database/models/session.py

"""Session persistence model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UserTrackingMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from palatium_ai.infrastructure.database.models.mcp_tool_call import McpToolCallORM


class SessionORM(UUIDPrimaryKeyMixin, TimestampMixin, UserTrackingMixin, Base):
    """Persistent conversation/session aggregate root."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("thread_id"),
        Index("ix_sessions_status_created_at", "status", "created_at"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=sa.text("'active'"),
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB(astext_type=sa.Text()),
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    tool_calls: Mapped[list[McpToolCallORM]] = relationship(back_populates="session")
