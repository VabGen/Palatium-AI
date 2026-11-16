# src/palatium_ai/infrastructure/database/models/memory_op.py

"""ORM for ``memory.ops`` durable queue (W11)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from palatium_ai.infrastructure.database.models.memory_entry import MEMORY_SCHEMA


class MemoryOpORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Platform memory op row — not FORCE RLS (system queue)."""

    __tablename__ = "ops"
    __table_args__ = (
        Index("ix_memory_ops_claim", "status", "available_at", "created_at"),
        {"schema": MEMORY_SCHEMA},
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_key: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    namespace_json: Mapped[str] = mapped_column(String(1024), nullable=False, default="[]")
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
