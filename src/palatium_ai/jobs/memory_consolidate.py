# src/palatium_ai/jobs/memory_consolidate.py

"""CLI entry: ``python -m palatium_ai.jobs.memory_consolidate`` (060, ADR 0002).

Out-of-band sleep consolidation: promote medium → long-term, then run the memory
retention sweep. Retention is dry-run unless ``--execute`` is passed to this CLI:
destructive retention stays an explicit operator decision (020).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from palatium_ai.application.services.memory_sleep_consolidation import SleepConsolidationService
from palatium_ai.application.services.retention import RetentionOrchestrator, retention_windows_from_settings
from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.domain.policies.retention import MEMORY_RETENTION_CLASSES
from palatium_ai.infrastructure.database.runtime import create_session_factory
from palatium_ai.infrastructure.retention import MemoryRetentionHandler
from palatium_ai.jobs.memory_promotion_factory import (
    build_memory_promotion_service,
    resolve_promotion_user_ids,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.policies.retention import RetentionClass, RetentionWindows
    from palatium_ai.domain.ports.retention import RetentionClassHandler

logger = get_logger(__name__)

EXIT_SUCCESS = 0
EXIT_INVALID_CONFIG = 2
EXIT_RUNTIME_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sleep-time consolidation: promote + memory retention sweep.",
    )
    parser.add_argument(
        "--user-id",
        action="append",
        dest="user_ids",
        default=[],
        help="RLS user_id scope to promote (repeatable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override MEMORY_PROMOTE_BATCH_LIMIT per user.",
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help=(
            "Discover every RLS owner with promotable rows (CronJob mode). "
            "Uses the SECURITY DEFINER RPC — a plain SELECT cannot see tenants."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply retention dispositions (default: plan only).",
    )
    parser.add_argument(
        "--skip-promote",
        action="store_true",
        help="Run only the retention sweep.",
    )
    parser.add_argument(
        "--skip-retention",
        action="store_true",
        help="Run only promote.",
    )
    return parser


def _emit(message: str, *, error: bool = False) -> None:
    """CLI operator output (CronJob logs); not application structlog."""
    stream = sys.stderr if error else sys.stdout
    print(message, file=stream)  # intentional CLI stdout/stderr for operators


def _memory_handlers(
    session_factory: async_sessionmaker[AsyncSession],
    windows: RetentionWindows,
) -> dict[RetentionClass, RetentionClassHandler]:
    return {
        retention_class: MemoryRetentionHandler(
            session_factory,
            retention_class=retention_class,
            windows=windows,
        )
        for retention_class in MEMORY_RETENTION_CLASSES
    }


async def _run(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    user_ids: list[str],
    all_users: bool,
    limit: int,
    execute: bool,
    skip_promote: bool,
    skip_retention: bool,
) -> int:
    if skip_promote and skip_retention:
        _emit("both --skip-promote and --skip-retention set — nothing to do", error=True)
        return EXIT_INVALID_CONFIG
    run_promote = not skip_promote and settings.memory.promote_enabled
    if not skip_promote and not settings.memory.promote_enabled:
        _emit("MEMORY_PROMOTE_ENABLED=false — promote skipped")
    if run_promote and not user_ids and not all_users:
        _emit("at least one --user-id or --all-users is required for promote", error=True)
        return EXIT_INVALID_CONFIG
    resolved_user_ids = (
        await resolve_promotion_user_ids(
            session_factory,
            explicit=user_ids,
            all_users=all_users,
            min_importance=settings.memory.promote_min_importance,
        )
        if run_promote
        else user_ids
    )
    if run_promote and not resolved_user_ids:
        _emit("no promotable owners found — promote skipped")
        run_promote = False

    windows = retention_windows_from_settings(settings)
    orchestrator = RetentionOrchestrator(windows=windows, handlers=_memory_handlers(session_factory, windows))
    promotion = build_memory_promotion_service(settings=settings, session_factory=session_factory) if run_promote else None
    service = SleepConsolidationService(promotion=promotion, retention=orchestrator)
    dry_run = not execute
    result = await service.run(
        user_ids=resolved_user_ids,
        limit=limit,
        dry_run=dry_run,
        run_promote=run_promote,
        run_retention=not skip_retention,
    )

    mode = "dry-run" if result.dry_run else "execute"
    _emit(f"memory consolidation ({mode})")
    for user_id, promoted in result.promoted.items():
        _emit(f"  - {user_id}: promoted={promoted}")
    if result.retention is not None:
        for report in result.retention.reports:
            detail = f" ({report.detail})" if report.detail else ""
            _emit(
                f"  - {report.retention_class}: action={report.action} "
                f"candidates={report.candidates} acted={report.acted} "
                f"held={report.held} failed={report.failed}{detail}"
            )
    return EXIT_SUCCESS


async def _async_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    limit = args.limit if args.limit is not None else settings.memory.promote_batch_limit
    engine, session_factory = create_session_factory(settings)
    try:
        return await _run(
            settings=settings,
            session_factory=session_factory,
            user_ids=[uid.strip() for uid in args.user_ids if uid.strip()],
            all_users=bool(args.all_users),
            limit=max(1, min(int(limit), 128)),
            execute=args.execute,
            skip_promote=args.skip_promote,
            skip_retention=args.skip_retention,
        )
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        logger.error("memory_consolidate.failed", error=str(exc))
        _emit(f"error: {exc}", error=True)
        return EXIT_RUNTIME_ERROR
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
