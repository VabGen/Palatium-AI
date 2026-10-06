# src/palatium_ai/infrastructure/database/runtime.py

"""SQLAlchemy runtime helpers for async engine and sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.core.resilience import RetryPolicy
from palatium_ai.infrastructure.database.resilience import (
    DB_BACKOFF_POLICY_INFO_KEY,
    ResilientAsyncSession,
)

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


def db_retry_policy(db_cfg: DatabaseConfig) -> RetryPolicy:
    """Retry budget for connection acquisition (``DB_RETRY_*``; 050: no magic numbers)."""
    return RetryPolicy(
        max_attempts=db_cfg.retry_attempts,
        initial_delay_seconds=db_cfg.retry_initial_delay_seconds,
        max_delay_seconds=db_cfg.retry_max_delay_seconds,
    )


def create_session_factory(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create the shared async engine and session factory for persistence.

    The factory yields :class:`ResilientAsyncSession`: a Postgres restart is retried
    briefly and, if it outlives the budget, surfaces as a typed 503 instead of an
    ASGI 500 (035). The retry policy travels through ``session.info`` so no call site
    has to pass it around.
    """
    should_echo_sql = settings.db.echo and settings.logging.level.upper() == "DEBUG"
    engine = create_async_engine(settings.db.async_dsn, echo=should_echo_sql, **engine_pool_kwargs(settings.db))
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=ResilientAsyncSession,
        info={DB_BACKOFF_POLICY_INFO_KEY: db_retry_policy(settings.db)},
    )
    # ``class_=`` narrows the generic to the subclass; repositories only need the
    # AsyncSession port, so the boundary widens it back explicitly (no `type: ignore`).
    session_factory = cast("async_sessionmaker[AsyncSession]", factory)
    return engine, session_factory
