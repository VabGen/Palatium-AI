#!/usr/bin/env python
"""Prompt-change eval gate: deterministic evals for affected agents (Phase 6, 075).

Usage (CI and locally):

    uv run python scripts/run_prompt_eval_gate.py --base-ref origin/dev
    uv run python scripts/run_prompt_eval_gate.py --changed src/palatium_ai/application/agents/critic/prompts.py
    uv run python scripts/run_prompt_eval_gate.py --base-ref origin/dev --metrics deepeval

Exit codes: 0 pass (or nothing affected), 1 eval regression, 2 configuration error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys

from pathlib import Path
from typing import Any

from palatium_ai.application.agents.evals.deepeval_grader import (
    DEEPEVAL_TASK_KEY,
    DeepEvalGrader,
    deepeval_installed,
    run_deepeval_evals,
)
from palatium_ai.application.agents.evals.judge_client import (
    assert_provider_independence,
    resolve_judge_provider,
)
from palatium_ai.application.agents.evals.prompt_gate import affected_agents, run_prompt_gate
from palatium_ai.application.agents.evals.runner import load_agent_tasks

_ARTIFACT_DEFAULT = "artifacts/prompt_evals.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prompt-change eval gate (deterministic + optional deepeval)")
    parser.add_argument("--changed", nargs="*", default=[], help="Changed repository paths (default: git diff)")
    parser.add_argument(
        "--base-ref",
        default="origin/dev",
        help="Git ref to diff against when --changed is empty (default: origin/dev)",
    )
    parser.add_argument(
        "--metrics",
        choices=("none", "deepeval"),
        default="none",
        help="Optional LLM metric backend for cases that opt in via deepeval blocks",
    )
    parser.add_argument("--report", default=_ARTIFACT_DEFAULT, help=f"JSON artifact path (default: {_ARTIFACT_DEFAULT})")
    parser.add_argument("--no-report", action="store_true", help="Skip writing the JSON artifact")
    return parser.parse_args()


def _changed_from_git(base_ref: str) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git executable not found")
    completed = subprocess.run(  # noqa: S603  # resolved executable, fixed argv, no shell
        [git, "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        msg = f"git diff against {base_ref} failed: {completed.stderr.strip()}"
        raise SystemExit(msg)
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _deepeval_task_counts(agents: tuple[str, ...]) -> dict[str, int]:
    return {agent: sum(1 for task in load_agent_tasks(agent) if DEEPEVAL_TASK_KEY in task) for agent in agents}


async def _run_deepeval(agents: tuple[str, ...], grader: DeepEvalGrader) -> dict[str, Any]:
    reports = {}
    for agent in agents:
        reports[agent] = await run_deepeval_evals(agent, grader=grader)
    return {
        "metric_backend": "deepeval",
        "tasks": _deepeval_task_counts(agents),
        "reports": [report.model_dump() for report in reports.values()],
        "failures": [f"{report.agent}/{detail}" for report in reports.values() for detail in report.details],
    }


def _write_artifact(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def _deepeval_stage(changed: list[str], payload: dict[str, Any]) -> list[str] | None:
    """Run the optional metric backend; ``None`` means "config error, exit 2"."""
    if not deepeval_installed():
        print('prompt_gate: --metrics deepeval requires `uv pip install "deepeval==<pinned>"` in an eval-only job')
        return None
    try:
        assert_provider_independence(
            judge_provider=resolve_judge_provider(),
            generator_provider=os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER"),
        )
    except ValueError as exc:
        print(f"prompt_gate: {exc}")
        return None

    agents = affected_agents(changed)
    counts = _deepeval_task_counts(agents)
    if not any(counts.values()):
        payload["deepeval"] = {"metric_backend": "deepeval", "skipped": "no cases opt in"}
        print("  deepeval: no cases opt in — skipped")
        return []

    deepeval_payload = await _run_deepeval(agents, DeepEvalGrader())
    payload["deepeval"] = deepeval_payload
    for agent, total in counts.items():
        print(f"  deepeval {agent}: {total} case(s)")
    return list(deepeval_payload["failures"])


async def _main() -> int:
    args = _parse_args()
    changed = list(args.changed) or _changed_from_git(args.base_ref)
    if not changed:
        print("prompt_gate: no changed paths — nothing to evaluate")
        return 0

    result = await run_prompt_gate(changed)
    payload: dict[str, Any] = {"deterministic": result.model_dump()}
    failures = list(result.failures)

    for report in result.reports:
        print(f"{report.agent}: {report.passed}/{report.total} passed (score={report.score:.3f})")
    print(f"prompt_gate: golden={result.golden_version} affected={','.join(result.affected_agents) or '-'}")
    for digest in result.digests:
        print(f"  prompt digest {digest.agent}: {digest.sha256[:16]}…")

    if args.metrics == "deepeval":
        # Fail-closed: the CI step requested metrics, so a missing key/package is an
        # error, not a silent downgrade to deterministic-only (035).
        metric_failures = await _deepeval_stage(changed, payload)
        if metric_failures is None:
            return 2
        failures.extend(metric_failures)

    payload["failures"] = failures
    payload["passed"] = not failures
    if not args.no_report:
        _write_artifact(args.report, payload)
        print(f"report: {args.report}")

    if failures:
        for failure in failures:
            print(f"  - {failure}")
        print("prompt_gate: FAIL")
        return 1
    print("prompt_gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
