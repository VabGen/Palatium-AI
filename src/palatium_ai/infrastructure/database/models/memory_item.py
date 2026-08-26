# src/palatium_ai/infrastructure/database/models/memory_item.py

"""Cross-thread memory item ORM (MemoryPort)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.infrastructure.database.base import (
    DEFAULT_DB_SCHEMA,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MemoryItemORM(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Namespaced key/value memory row (PostgresStore-shaped)."""

    __tablename__ = "memory_items"
    __table_args__ = (
        UniqueConstraint(
            "namespace",
            "key",
            name="uq_memory_items_namespace_key",
        ),
        Index("ix_memory_items_namespace", "namespace"),
        {"schema": DEFAULT_DB_SCHEMA},
    )

    namespace: Mapped[str] = mapped_column(String(512), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
