# src/palatium_ai/infrastructure/database/models/memory_entry.py

"""Episodic memory ORM — schema ``memory``, table ``entries`` (060)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.core.types.embeddings import MEMORY_EMBEDDING_DIM
from palatium_ai.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MEMORY_SCHEMA = "memory"


class MemoryEntryORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Medium-term memory row with pgvector + FTS (060)."""

    __tablename__ = "entries"
    __table_args__ = (
        UniqueConstraint("user_id", "namespace", "entry_key", name="uq_memory_entries_user_ns_key"),
        Index("ix_memory_entries_user_namespace", "user_id", "namespace"),
        {"schema": MEMORY_SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    namespace: Mapped[str] = mapped_column(String(512), nullable=False)
    entry_key: Mapped[str] = mapped_column(String(256), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fact")
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    contains_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(MEMORY_EMBEDDING_DIM), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
