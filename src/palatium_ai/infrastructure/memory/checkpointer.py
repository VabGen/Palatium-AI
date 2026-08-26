# src/palatium_ai/infrastructure/memory/checkpointer.py

"""LangGraph checkpointer factory (MemorySaver | AsyncPostgresSaver)."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.memory import MemorySaver

from palatium_ai.core.logging import get_logger
from palatium_ai.infrastructure.memory.checkpoint_serde import build_checkpoint_serde

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from palatium_ai.core.config.settings import Settings

logger = get_logger(__name__)

_SETUP_TIMEOUT_SECONDS = 15.0


@dataclass(slots=True)
class CheckpointerHandle:
    """Compiled saver + optional async closer (pool shutdown)."""

    saver: BaseCheckpointSaver[Any]
    aclose: Callable[[], Awaitable[None]] | None = None


def ensure_psycopg_compatible_loop() -> None:
    """Psycopg async requires SelectorEventLoop on Windows (not Proactor)."""
    if sys.platform != "win32":
        return
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception as exc:
        logger.debug("Could not set WindowsSelectorEventLoopPolicy", error=str(exc))


def _memory_saver() -> MemorySaver:
    """In-process saver with the same msgpack allowlist as Postgres."""
    return MemorySaver(serde=build_checkpoint_serde())


async def create_checkpointer(settings: Settings) -> CheckpointerHandle:
    """Build checkpointer; fall back to MemorySaver if Postgres saver unavailable."""
    serde = build_checkpoint_serde()
    if not settings.memory.use_postgres_checkpointer:
        logger.info("LangGraph checkpointer: MemorySaver (process-local)")
        return CheckpointerHandle(saver=_memory_saver())

    ensure_psycopg_compatible_loop()

    try:
        # Optional soft-deps: langgraph-checkpoint-postgres + psycopg-pool.
        # Runtime falls back to MemorySaver when the env lacks them.
        from langgraph.checkpoint.postgres.aio import (  # pyright: ignore[reportMissingImports]
            AsyncPostgresSaver,
        )
        from psycopg_pool import AsyncConnectionPool  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        logger.warning(
            "LangGraph Postgres checkpointer unavailable; using MemorySaver",
            error=str(exc),
        )
        return CheckpointerHandle(saver=_memory_saver())

    pool: AsyncConnectionPool | None = None
    try:
        pool = AsyncConnectionPool(
            conninfo=settings.db.psycopg_dsn,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            min_size=1,
            max_size=4,
            open=False,
            timeout=5.0,
        )
        await asyncio.wait_for(pool.open(), timeout=_SETUP_TIMEOUT_SECONDS)
        saver = AsyncPostgresSaver(conn=cast("Any", pool), serde=serde)
        await asyncio.wait_for(saver.setup(), timeout=_SETUP_TIMEOUT_SECONDS)
    except Exception as exc:
        if pool is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(pool.close(), timeout=5.0)
        logger.warning(
            "LangGraph AsyncPostgresSaver setup failed; using MemorySaver",
            error=str(exc),
        )
        return CheckpointerHandle(saver=_memory_saver())

    opened_pool = pool

    async def _close() -> None:
        await opened_pool.close()

    logger.info("LangGraph checkpointer: AsyncPostgresSaver")
    return CheckpointerHandle(saver=saver, aclose=_close)
