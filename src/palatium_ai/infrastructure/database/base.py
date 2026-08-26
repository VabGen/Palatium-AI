# src/palatium_ai/infrastructure/database/base.py

"""Shared SQLAlchemy metadata and declarative base."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    MetaData,
    String,
    Uuid,
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

DEFAULT_DB_SCHEMA = "palatium_ai"
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy ORM models."""

    metadata = metadata


class UUIDPrimaryKeyMixin:
    """Reusable UUID primary key for ORM entities."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    """UTC creation/update timestamps for ORM entities."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=sql_text("TIMEZONE('utc', now())"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=sql_text("TIMEZONE('utc', now())"),
    )


class UserTrackingMixin:
    """Optional user ownership / attribution fields."""

    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
