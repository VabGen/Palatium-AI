# src/palatium_ai/jobs/memory_promote.py

"""CLI entry: ``python -m palatium_ai.jobs.memory_promote`` (Wave M3 / ADR 0002).

Out-of-band medium → long-term promote. Never called from extract worker.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.infrastructure.database.runtime import create_session_factory
from palatium_ai.jobs.memory_promotion_factory import (
    build_memory_promotion_service,
    resolve_promotion_user_ids,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.core.config.settings import Settings

logger = get_logger(__name__)

EXIT_SUCCESS = 0
EXIT_INVALID_CONFIG = 2
EXIT_RUNTIME_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote medium-term memory into Neo4j (batch; not extract).",
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
    return parser


def _emit(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(message, file=stream)  # intentional CLI stdout/stderr for operators


async def _run(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    user_ids: list[str],
    all_users: bool,
    limit: int,
) -> int:
    if not settings.memory.promote_enabled:
        _emit("MEMORY_PROMOTE_ENABLED=false — nothing to do")
        return EXIT_SUCCESS
    if not user_ids and not all_users:
        _emit("at least one --user-id or --all-users is required", error=True)
        return EXIT_INVALID_CONFIG
    resolved = await resolve_promotion_user_ids(
        session_factory,
        explicit=user_ids,
        all_users=all_users,
        min_importance=settings.memory.promote_min_importance,
    )
    if not resolved:
        _emit("no promotable owners found — nothing to do")
        return EXIT_SUCCESS
    _emit(f"owners={len(resolved)}")
    service = build_memory_promotion_service(
        settings=settings,
        session_factory=session_factory,
    )
    total = 0
    for user_id in resolved:
        promoted = await service.run_batch(user_id=user_id, limit=limit)
        total += promoted
        _emit(f"user_id={user_id} promoted={promoted}")
        logger.info("memory_promote.batch", user_id=user_id, promoted=promoted)
    _emit(f"total_promoted={total}")
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
        )
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        agent_metrics.record_memory_promote_error(error_type=type(exc).__name__)
        logger.error("memory_promote.failed", error=str(exc))
        _emit(f"error: {exc}", error=True)
        return EXIT_RUNTIME_ERROR
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
