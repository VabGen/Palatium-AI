# src/palatium_ai/infrastructure/database/models/memory_extract_job.py

"""ORM for ``memory.extract_jobs`` durable queue (Wave M3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from palatium_ai.infrastructure.database.models.memory_entry import MEMORY_SCHEMA


class MemoryExtractJobORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Platform extract job row — not FORCE RLS (system queue)."""

    __tablename__ = "extract_jobs"
    __table_args__ = (
        UniqueConstraint("thread_id", "task_id", name="uq_memory_extract_jobs_thread_task"),
        Index("ix_memory_extract_jobs_claim", "status", "available_at", "created_at"),
        {"schema": MEMORY_SCHEMA},
    )

    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
