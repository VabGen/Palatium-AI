#!/usr/bin/env python
"""Run deterministic agent evals and enforce baseline gate (075)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from palatium_ai.application.agents.evals.report import (
    write_report,
)
from palatium_ai.application.agents.evals.runner import (
    assert_baseline_gate,
    build_suite_report,
    run_all_agent_evals,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run agent eval suite (deterministic)")
    parser.add_argument(
        "--report",
        default="artifacts/agent_evals.json",
        help="Write JSON report to this path (default: artifacts/agent_evals.json)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing JSON report file",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    reports = await run_all_agent_evals()
    for agent, report in sorted(reports.items()):
        print(f"{agent}: {report.passed}/{report.total} passed (score={report.score:.3f})")
        for detail in report.details:
            print(f"  - {detail}")
    assert_baseline_gate(reports)
    if not args.no_report:
        suite = build_suite_report(reports)
        write_report(args.report, suite)
        print(f"report: {args.report}")
    print("agent_evals: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
