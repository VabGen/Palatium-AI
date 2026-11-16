# src/palatium_ai/infrastructure/memory/checkpointer.py

"""LangGraph checkpointer factory (MemorySaver | AsyncPostgresSaver)."""

from __future__ import annotations

import asyncio
import contextlib
import selectors
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

#: Windows needs an explicit ``SelectSelector`` loop for psycopg async (Proactor fails).
#: Kept as a constant instead of an inline ``sys.platform`` test: mypy narrows
#: ``sys.platform`` to the target platform's literal, which would mark one branch
#: unreachable on the other OS — the check has to type-check the same on win32 and POSIX.
_IS_WINDOWS = sys.platform == "win32"


@dataclass(slots=True)
class CheckpointerHandle:
    """Compiled saver + optional async closer (pool shutdown)."""

    saver: BaseCheckpointSaver[Any]
    aclose: Callable[[], Awaitable[None]] | None = None


def create_psycopg_event_loop() -> asyncio.AbstractEventLoop:
    """Zero-arg factory for ``asyncio.run(loop_factory=...)`` / uvicorn ``loop=``.

    Purpose: psycopg's async connections need ``add_reader``/``add_writer`` on the
    running loop, and the generic ``ProactorEventLoop`` (the asyncio default on win32)
    does not implement them — the pool then fails at connect time with a traceback that
    points at psycopg, not at the loop. This factory returns a ``SelectorEventLoop``
    bound to ``SelectSelector`` so the saver works on Windows the same way it does on
    POSIX.

    uvicorn's built-in ``asyncio`` factory returns the platform default, hence the
    explicit factory in ``main.py``. Custom ``loop=module:attr`` is passed straight to
    ``asyncio.run(loop_factory=...)``, so this must return a loop — not a meta-factory.

    Event-loop *policies* are deliberately not used: deprecated in Python 3.14 and
    removed in 3.16, ``loop_factory`` is the replacement hook (060).
    """
    if _IS_WINDOWS:
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.SelectorEventLoop()


def psycopg_loop_factory_spec() -> str:
    """``module:attr`` reference to :func:`create_psycopg_event_loop` for uvicorn.

    uvicorn types ``loop`` as ``LoopFactoryType | str`` and resolves a non-name value with
    ``import_from_string`` — a callable cannot be passed, so the entry point needs a
    string. It is *derived* from the function object instead of being written out by
    hand: renaming or moving the factory renames the reference, so the two cannot drift
    into a startup failure.
    """
    return f"{create_psycopg_event_loop.__module__}:{create_psycopg_event_loop.__qualname__}"


def is_psycopg_compatible_loop(loop: object) -> bool:
    """True when ``loop`` implements ``add_reader``/``add_writer`` (SelectorEventLoop).

    Split out from :func:`ensure_psycopg_compatible_loop` so the verdict is unit-testable
    on every OS: on POSIX asyncio always builds a selector loop, which would leave the
    diagnostic's "wrong loop" branch unexercised in CI.
    """
    return isinstance(loop, asyncio.SelectorEventLoop)


def ensure_psycopg_compatible_loop() -> bool:
    """Diagnose a running Windows loop; do not set deprecated event-loop policies.

    Returns ``True`` when nothing is wrong (not Windows, no running loop, or a
    ``SelectorEventLoop``) and ``False`` after logging a warning when the running loop
    cannot serve psycopg. The boolean lets a caller decide whether a wrong loop is fatal
    for its own path (e.g. ``create_checkpointer`` is only affected when the Postgres
    saver is enabled), without re-implementing the platform test.

    psycopg async needs ``SelectorEventLoop`` on Windows (not Proactor). Python
    3.14 deprecates policies (removed in 3.16) — create the loop via
    ``create_psycopg_event_loop`` (``asyncio.run(..., loop_factory=...)`` or
    uvicorn ``loop=`` in ``main.py``). Call this after a loop exists to log a
    warning if the wrong loop type is already running.
    """
    if not _IS_WINDOWS:
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return True
    if is_psycopg_compatible_loop(loop):
        return True
    logger.warning(
        "Running event loop is not SelectorEventLoop; "
        "AsyncPostgresSaver/psycopg may fail on Windows. "
        "Pass create_psycopg_event_loop to asyncio.run(loop_factory=...) "
        "or uvicorn loop=",
        loop_type=type(loop).__name__,
    )
    return False


def _memory_saver() -> MemorySaver:
    """In-process saver with the same msgpack allowlist as Postgres."""
    return MemorySaver(serde=build_checkpoint_serde())


async def create_checkpointer(settings: Settings) -> CheckpointerHandle:
    """Build checkpointer; fall back to MemorySaver if Postgres saver unavailable."""
    serde = build_checkpoint_serde()
    if not settings.postgres_checkpointer_enabled:
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
    except Exception as exc:  # noqa: BLE001  # setup failure falls back to MemorySaver (ADR 0003)
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
