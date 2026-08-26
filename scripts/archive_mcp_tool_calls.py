"""Soft-archive MCP tool call rows older than a retention window."""

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
    read_optional_str_env,
    write_retention_audit,
)
from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
from palatium_ai.infrastructure.database.runtime import create_session_factory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive mcp_tool_calls older than N days. Dry-run by default.",
    )
    parser.add_argument(
        "--days",
        type=int,
        required=False,
        help="Archive rows whose created_at is older than this number of days.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Optional maximum number of rows to process in one run.",
    )
    parser.add_argument(
        "--event",
        type=str,
        default=None,
        help="Optional event filter, e.g. mcp_tool_failed.",
    )
    parser.add_argument(
        "--server-name",
        type=str,
        default=None,
        help="Optional MCP server filter.",
    )
    parser.add_argument(
        "--is-error",
        choices=("true", "false"),
        default=None,
        help="Optional error-state filter.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually archive rows. Without this flag the script only previews the count.",
    )
    return parser


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "true"


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    repository = McpToolCallRepository(session_factory)

    try:
        cutoff = datetime.now(UTC) - timedelta(days=args.days)
        affected_rows = await repository.archive_older_than(
            older_than=cutoff,
            dry_run=not args.execute,
            batch_size=args.batch_size,
            event=args.event,
            is_error=_parse_bool(args.is_error),
            server_name=args.server_name,
        )
    finally:
        await engine.dispose()

    await write_retention_audit(
        "mcp_tool_calls_archive_executed" if args.execute else "mcp_tool_calls_archive_preview",
        {
            "days": args.days,
            "batch_size": args.batch_size or "",
            "event_filter": args.event or "",
            "server_name_filter": args.server_name or "",
            "is_error_filter": args.is_error or "",
            "affected_rows": affected_rows,
        },
    )

    mode = "ARCHIVE" if args.execute else "DRY-RUN"
    print(f"[{mode}] mcp_tool_calls older than {args.days} day(s): {affected_rows} row(s) matched")
    if args.event is not None:
        print(f"  event={args.event}")
    if args.server_name is not None:
        print(f"  server_name={args.server_name}")
    if args.is_error is not None:
        print(f"  is_error={args.is_error}")
    if not args.execute:
        print("Re-run with --execute to apply the archive.")
    return int(EXIT_SUCCESS)


def main() -> int:
    """Parse arguments, resolve env fallbacks, and run the archive workflow."""
    parser = _build_parser()
    try:
        args = parser.parse_args()
        args.days = args.days if args.days is not None else read_int_env("MCP_RETENTION_ARCHIVE_DAYS")
        args.batch_size = args.batch_size if args.batch_size is not None else read_int_env("MCP_RETENTION_BATCH_SIZE")
        args.event = args.event if args.event is not None else read_optional_str_env("MCP_RETENTION_EVENT")
        args.server_name = (
            args.server_name if args.server_name is not None else read_optional_str_env("MCP_RETENTION_SERVER_NAME")
        )
        args.is_error = args.is_error if args.is_error is not None else read_optional_str_env("MCP_RETENTION_IS_ERROR")
        env_execute = read_optional_bool_env("MCP_RETENTION_EXECUTE")
        args.execute = args.execute or bool(env_execute)

        if args.days is None:
            parser.error("--days is required (or set MCP_RETENTION_ARCHIVE_DAYS)")
        if args.days < 1:
            parser.error("--days must be >= 1")
        if args.batch_size is not None and args.batch_size < 1:
            parser.error("--batch-size must be >= 1")
        return int(asyncio.run(_run(args)))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else int(EXIT_INVALID_CONFIG)
    except Exception as exc:
        print(f"[ERROR] archive_mcp_tool_calls failed: {exc}", file=sys.stderr)
        return int(EXIT_RUNTIME_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
