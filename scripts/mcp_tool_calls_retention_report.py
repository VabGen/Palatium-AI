"""Generate a retention report for MCP tool call persistence."""

from __future__ import annotations

import argparse
import asyncio
import sys

from datetime import UTC, datetime, timedelta

from _retention_common import (
    EXIT_INVALID_CONFIG,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    read_int_env,
    write_retention_audit,
)

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
from palatium_ai.infrastructure.database.runtime import create_session_factory


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show retention counters for mcp_tool_calls.",
    )
    parser.add_argument(
        "--purge-years",
        type=int,
        required=False,
        help="Count archived rows eligible for purge older than this number of years.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine, session_factory = create_session_factory(settings)
    repository = McpToolCallRepository(session_factory)

    try:
        purge_cutoff = datetime.now(UTC) - timedelta(days=365 * args.purge_years)
        report = await repository.retention_report(purge_older_than=purge_cutoff)
    finally:
        await engine.dispose()

    await write_retention_audit(
        "mcp_tool_calls_retention_report_generated",
        {
            "purge_years": args.purge_years,
            "active": report["active"],
            "archived": report["archived"],
            "purge_candidates": report["purge_candidates"],
        },
    )

    print("MCP tool calls retention report")
    print(f"  active: {report['active']}")
    print(f"  archived: {report['archived']}")
    print(f"  purge_candidates: {report['purge_candidates']}")
    print(f"  purge_years: {args.purge_years}")
    return int(EXIT_SUCCESS)


def main() -> int:
    """CLI entry point for generating MCP tool call retention report."""
    parser = _build_parser()
    try:
        args = parser.parse_args()
        args.purge_years = (
            args.purge_years if args.purge_years is not None else read_int_env("MCP_RETENTION_PURGE_YEARS")
        )
        if args.purge_years is None:
            parser.error("--purge-years is required (or set MCP_RETENTION_PURGE_YEARS)")
        if args.purge_years < 1:
            parser.error("--purge-years must be >= 1")
        return int(asyncio.run(_run(args)))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else int(EXIT_INVALID_CONFIG)
    except Exception as exc:
        print(f"[ERROR] mcp_tool_calls_retention_report failed: {exc}", file=sys.stderr)
        return int(EXIT_RUNTIME_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
