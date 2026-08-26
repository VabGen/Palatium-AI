# src/palatium_ai/infrastructure/database/models/mcp_tool_call.py

"""MCP tool call persistence model."""

from __future__ import annotations
# ruff: noqa: I001

from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
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
    from palatium_ai.infrastructure.database.models.session import SessionORM


class McpToolCallORM(UUIDPrimaryKeyMixin, TimestampMixin, UserTrackingMixin, Base):
    """Persistent record of a single MCP tool invocation."""

    __tablename__ = "mcp_tool_calls"
    __table_args__ = (
        Index("ix_mcp_tool_calls_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_mcp_tool_calls_session_id_created_at", "session_id", "created_at"),
        Index("ix_mcp_tool_calls_archived_at", "archived_at"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    conversation_id: Mapped[str] = mapped_column(String(256), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{DEFAULT_DB_SCHEMA}.sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    server_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)

    arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB(astext_type=sa.Text()),
        nullable=False,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    content: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(astext_type=sa.Text()),
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )

    is_error: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    session: Mapped[SessionORM | None] = relationship(back_populates="tool_calls")

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
