# src/palatium_ai/infrastructure/database/runtime.py

"""SQLAlchemy runtime helpers for async engine and sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from palatium_ai.core.config.database import DatabaseConfig
    from palatium_ai.core.config.settings import Settings


class EnginePoolKwargs(TypedDict):
    """Connection-pool options for ``create_async_engine`` (050: from config, not magic numbers)."""

    pool_size: int
    max_overflow: int
    pool_pre_ping: bool
    pool_timeout: float


def engine_pool_kwargs(db_cfg: DatabaseConfig) -> EnginePoolKwargs:
    """Pool options shared by the runtime engine and the short-lived init engine.

    Keeps ``DB_POOL_*`` from being dead config: operators tuning env vars get real effect.
    """
    return {
        "pool_size": db_cfg.pool_size,
        "max_overflow": db_cfg.max_overflow,
        "pool_pre_ping": db_cfg.pool_pre_ping,
        "pool_timeout": db_cfg.pool_timeout_seconds,
    }


def create_session_factory(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create the shared async engine and session factory for persistence."""
    should_echo_sql = settings.db.echo and settings.logging.level.upper() == "DEBUG"
    engine = create_async_engine(settings.db.async_dsn, echo=should_echo_sql, **engine_pool_kwargs(settings.db))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
