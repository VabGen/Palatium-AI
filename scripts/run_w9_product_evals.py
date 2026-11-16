#!/usr/bin/env python
"""W9 product-quality live evals entrypoint (outside PR CI — nightly / dispatch)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from pathlib import Path

from palatium_ai.application.agents.evals.judge_client import EvalJudgeClientFactory
from palatium_ai.application.agents.evals.product_quality.runner import run_suite
from palatium_ai.core.config.settings import get_settings
from palatium_ai.domain.ports.llm import LLMPort
from palatium_ai.infrastructure.llm.factory import create_llm_client

_SUITES = ("semantic", "context", "multi_turn", "formatter")


def _llm_factory(provider: str) -> LLMPort:
    return create_llm_client(get_settings(), provider)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run W9 product-quality live evals")
    parser.add_argument(
        "--suite",
        choices=[*_SUITES, "all"],
        default="all",
        help="Suite to run (default: all)",
    )
    parser.add_argument(
        "--mode",
        choices=["live_smoke", "live_full"],
        default="live_full",
        help="live_smoke = ≤3 cases/suite; live_full = all cases",
    )
    parser.add_argument(
        "--report",
        default="artifacts/w9_product_evals.json",
        help="Write JSON report path",
    )
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument(
        "--live-judge",
        action="store_true",
        help="Enable LLM-judge after rule gate (PALATIUM_EVAL_LIVE_JUDGE=1)",
    )
    parser.add_argument(
        "--skip-baseline-assert",
        action="store_true",
        help="Measure pass_rate without comparing to pinned floors (Phase 2–3)",
    )
    return parser.parse_args()


def _smoke_case_ids(suite: str) -> set[str] | None:
    """≤3 cases/suite, stratified by agent/request_type so smoke is not analyst-only."""
    from palatium_ai.application.agents.evals.product_quality.loader import load_cases

    cases = load_cases(suite)  # type: ignore[arg-type]
    by_key: dict[str, list[str]] = {}
    for case in cases:
        key = str(case.input.get("request_type") or case.scenario) if suite == "formatter" else case.agent
        by_key.setdefault(key, []).append(case.id)
    picked: list[str] = []
    # Round-robin across keys until 3 ids.
    while len(picked) < 3 and any(by_key.values()):
        for key in list(by_key):
            if not by_key[key]:
                continue
            picked.append(by_key[key].pop(0))
            if len(picked) >= 3:
                break
    return set(picked)


async def _main() -> int:
    args = _parse_args()
    if os.environ.get("PALATIUM_LIVE_EVAL", "").strip() not in {"1", "true", "yes"}:
        print("PALATIUM_LIVE_EVAL must be 1 for live W9 (cassette substitution forbidden)")
        return 2
    if args.live_judge:
        os.environ["PALATIUM_EVAL_LIVE_JUDGE"] = "1"

    settings = get_settings()
    llm = create_llm_client(settings)
    factory: EvalJudgeClientFactory = _llm_factory
    generator_provider = settings.llm.default_provider
    os.environ.setdefault("PALATIUM_EVAL_AGENT_PROVIDER", generator_provider)
    print(f"generator_provider={generator_provider}")

    suites = _SUITES if args.suite == "all" else (args.suite,)
    reports: dict[str, object] = {}
    failed = False
    for suite in suites:
        case_ids = _smoke_case_ids(suite) if args.mode == "live_smoke" else None
        report = await run_suite(
            suite,  # type: ignore[arg-type]
            llm=llm,
            llm_factory=factory,
            case_ids=case_ids,
        )
        print(f"{suite}: pass_rates={dict(report.pass_rate_by_key)}")
        for outcome in report.outcomes:
            mark = "PASS" if outcome.passed else "FAIL"
            print(f"  [{mark}] {outcome.case_id}: {outcome.details}")
        if not args.skip_baseline_assert:
            try:
                report.assert_baselines()
            except AssertionError as exc:
                print(f"{suite}: BASELINE FAIL — {exc}")
                failed = True
        reports[suite] = {
            "mode": args.mode,
            "generator_provider": generator_provider,
            "pass_rate_by_key": dict(report.pass_rate_by_key),
            "outcomes": [
                {
                    "case_id": o.case_id,
                    "agent": o.agent,
                    "passed": o.passed,
                    "score": o.score,
                    "details": o.details,
                    "rule_passed": o.rule_passed,
                    "judge_passed": o.judge_passed,
                    "answer": (o.answer[:500] if o.answer else ""),
                }
                for o in report.outcomes
            ],
        }

    if not args.no_report:
        path = Path(args.report)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        payload = json.dumps(reports, ensure_ascii=False, indent=2)
        await asyncio.to_thread(path.write_text, payload, "utf-8")
        print(f"report: {path}")

    if failed:
        print("w9_product_evals: FAIL")
        return 1
    print("w9_product_evals: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
