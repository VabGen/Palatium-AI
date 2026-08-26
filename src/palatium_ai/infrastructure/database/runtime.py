# src/palatium_ai/infrastructure/database/runtime.py

"""SQLAlchemy runtime helpers for async engine and sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


def create_session_factory(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create the shared async engine and session factory for persistence."""
    should_echo_sql = settings.db.echo and settings.logging.level.upper() == "DEBUG"
    engine = create_async_engine(settings.db.async_dsn, echo=should_echo_sql)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
