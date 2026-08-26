"""Purge archived MCP tool call rows older than a retention window."""

from __future__ import annotations
# ruff: noqa: I001

import argparse
import asyncio
import sys

from datetime import UTC, datetime, timedelta

from _retention_common import (
    EXIT_INVALID_CONFIG,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    read_int_env,
    read_optional_bool_env,
    write_retention_audit,
)
from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
from palatium_ai.infrastructure.database.runtime import create_session_factory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete archived mcp_tool_calls older than N years. Dry-run by default.",
    )
    parser.add_argument(
        "--years",
        type=int,
        required=False,
        help="Delete records whose archived_at is older than this number of years.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Optional maximum number of rows to process in one run.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete rows. Without this flag the script only previews the count.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    repository = McpToolCallRepository(session_factory)

    try:
        cutoff = datetime.now(UTC) - timedelta(days=365 * args.years)
        affected_rows = await repository.purge_archived_older_than(
            older_than=cutoff,
            dry_run=not args.execute,
            batch_size=args.batch_size,
        )
    finally:
        await engine.dispose()

    await write_retention_audit(
        "mcp_tool_calls_purge_executed" if args.execute else "mcp_tool_calls_purge_preview",
        {
            "years": args.years,
            "batch_size": args.batch_size or "",
            "affected_rows": affected_rows,
        },
    )

    mode = "DELETE" if args.execute else "DRY-RUN"
    print(f"[{mode}] archived mcp_tool_calls older than {args.years} year(s): {affected_rows} row(s) matched")
    if not args.execute:
        print("Re-run with --execute to apply the deletion.")
    return int(EXIT_SUCCESS)


def main() -> int:
    """Parse arguments, resolve env fallbacks, and run the purge workflow."""
    parser = _build_parser()
    try:
        args = parser.parse_args()
        args.years = args.years if args.years is not None else read_int_env("MCP_RETENTION_PURGE_YEARS")
        args.batch_size = args.batch_size if args.batch_size is not None else read_int_env("MCP_RETENTION_BATCH_SIZE")
        env_execute = read_optional_bool_env("MCP_RETENTION_EXECUTE")
        args.execute = args.execute or bool(env_execute)

        if args.years is None:
            parser.error("--years is required (or set MCP_RETENTION_PURGE_YEARS)")
        if args.years < 1:
            parser.error("--years must be >= 1")
        if args.batch_size is not None and args.batch_size < 1:
            parser.error("--batch-size must be >= 1")
        return int(asyncio.run(_run(args)))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else int(EXIT_INVALID_CONFIG)
    except Exception as exc:
        print(f"[ERROR] purge_archived_mcp_tool_calls failed: {exc}", file=sys.stderr)
        return int(EXIT_RUNTIME_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
