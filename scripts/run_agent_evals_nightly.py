#!/usr/bin/env python
"""Nightly agent evals entrypoint (llm_judge tasks — outside PR CI)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from palatium_ai.application.agents.evals.report import write_report
from palatium_ai.application.agents.evals.runner import (
    assert_nightly_baseline_gate,
    build_suite_report,
    load_nightly_tasks,
    run_all_nightly_evals,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run nightly llm_judge agent evals")
    parser.add_argument(
        "--report",
        default="artifacts/agent_evals_nightly.json",
        help="Write JSON report to this path (default: artifacts/agent_evals_nightly.json)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing JSON report file",
    )
    parser.add_argument(
        "--live-judge",
        action="store_true",
        help="Enable live llm_judge (sets PALATIUM_EVAL_LIVE_JUDGE=1)",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    if args.live_judge:
        import os

        os.environ["PALATIUM_EVAL_LIVE_JUDGE"] = "1"
    tasks = load_nightly_tasks()
    if not tasks:
        print("agent_evals_nightly: no llm_judge tasks configured (SKIP)")
        return 0

    reports = await run_all_nightly_evals()
    report = reports["nightly"]
    print(f"nightly: {report.passed}/{report.total} passed (score={report.score:.3f})")
    for detail in report.details:
        print(f"  - {detail}")

    if report.passed != report.total:
        print("agent_evals_nightly: FAIL")
        return 1

    assert_nightly_baseline_gate(reports)

    if not args.no_report:
        suite = build_suite_report(reports)
        write_report(args.report, suite)
        print(f"report: {args.report}")
    print("agent_evals_nightly: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
