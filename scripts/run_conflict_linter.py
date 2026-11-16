#!/usr/bin/env python
"""Prompt conflict-linter CLI (same-prompt v1) — backlog §2.

Modes:
  --fixtures   regression suite (recall / FP gates)
  --audit      scan AUDIT_PROMPT_REVISIONS
  --judge      heuristic | none  (llm reserved; needs PALATIUM_CONFLICT_JUDGE=1 later)

Exit codes:
  0 — fixtures pass gates (and audit soft-only / clean)
  1 — fixture gate fail or audit hard findings (when --strict)
  Non-blocking CI uses continue-on-error until cutover 2026-12-19.
"""

from __future__ import annotations

import argparse
import json
import sys

from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from palatium_ai.application.agents.evals.conflict_linter.fixtures import (  # noqa: E402
    fixture_metrics,
    load_manifest,
    run_fixture_suite,
)
from palatium_ai.application.agents.evals.conflict_linter.judge import HeuristicJudge  # noqa: E402
from palatium_ai.application.agents.evals.conflict_linter.models import ConflictFinding  # noqa: E402
from palatium_ai.application.agents.evals.conflict_linter.noqa import count_noqa_markers  # noqa: E402
from palatium_ai.application.agents.evals.conflict_linter.policy import (  # noqa: E402
    CUTOVER_DATE,
    FIXTURE_FLOOR,
    NOQA_MAX,
    TRIAGED_SOFT_MUST_MAY,
    soft_metric_breakdown,
)
from palatium_ai.application.agents.evals.conflict_linter.scan import scan_audit_revisions  # noqa: E402
from palatium_ai.application.agents.evals.prompt_revisions import AUDIT_PROMPT_REVISIONS  # noqa: E402

_RECALL_MIN = 0.8  # ≥ 4/5
_FP_MAX = 0.2
_SRC = _ROOT / "src" / "palatium_ai"


def _print_findings(title: str, findings: Sequence[ConflictFinding]) -> None:
    print(title)
    if not findings:
        print("  (none)")
        return
    for item in findings:
        print(f"  {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="Run 5+5 fixture gates")
    parser.add_argument("--audit", action="store_true", help="Scan AUDIT_PROMPT_REVISIONS")
    parser.add_argument(
        "--judge",
        choices=("none", "heuristic"),
        default="heuristic",
        help="Semantic judge on fixtures (llm deferred)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on audit hard findings (default: report only until CI cutover)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_ROOT / "artifacts" / "conflict_linter.json",
        help="JSON report path",
    )
    args = parser.parse_args(argv)
    if not args.fixtures and not args.audit:
        args.fixtures = True
        args.audit = True

    report: dict[str, object] = {"mode": "same_prompt", "gates": {}, "audit": {}, "fixtures": {}}
    exit_code = 0

    if args.fixtures:
        suite_report, results = run_fixture_suite()
        cases = load_manifest()
        metrics = fixture_metrics(results, cases)

        judge_hits = 0
        conflict_cases = [c for c in cases if c.expected == "conflict"]
        if args.judge == "heuristic":
            judge = HeuristicJudge()
            for case in conflict_cases:
                from palatium_ai.application.agents.evals.conflict_linter.fixtures import fixture_text

                text = fixture_text(case)
                path = f"tests/fixtures/conflicts/{case.relative_path}"
                # Combine static (already in results) with judge for recall accounting.
                static_ok = results.get(case.fixture_id, False)
                judged = judge.judge(text, path=path, prompt_id=case.fixture_id)
                if static_ok or any(f.severity == "hard" for f in judged):
                    judge_hits += 1
                    results[case.fixture_id] = True
            metrics = fixture_metrics(results, cases)
            metrics["judge_recall"] = judge_hits / len(conflict_cases) if conflict_cases else 1.0

        report["fixtures"] = {
            "results": results,
            "metrics": metrics,
            "findings": [f.model_dump() for f in suite_report.findings],
        }
        n_conflict = sum(1 for c in cases if c.expected == "conflict")
        n_non = sum(1 for c in cases if c.expected == "non_conflict")
        print(
            f"fixtures: recall={metrics['recall']:.2f} "
            f"fp_rate={metrics['fp_rate']:.2f} "
            f"judge_recall={metrics.get('judge_recall', metrics['recall']):.2f} "
            f"(n={n_conflict}+{n_non}; floor={FIXTURE_FLOOR}+{FIXTURE_FLOOR}, not ceiling)"
        )
        if metrics["recall"] < _RECALL_MIN or metrics["fp_rate"] > _FP_MAX:
            print("fixture gates FAILED", file=sys.stderr)
            exit_code = 1
        if metrics.get("judge_recall", 1.0) < _RECALL_MIN:
            print("judge recall FAILED", file=sys.stderr)
            exit_code = 1

    if args.audit:
        audit = scan_audit_revisions()
        active = list(audit.active)
        hard = [f for f in active if f.severity == "hard"]
        soft = [f for f in active if f.severity == "soft"]
        soft_raw, soft_triaged, soft_new = soft_metric_breakdown(soft)
        noqa_total = 0
        for revision in AUDIT_PROMPT_REVISIONS:
            noqa_total += count_noqa_markers((_SRC / revision.relative_path).read_text(encoding="utf-8"))
        report["audit"] = {
            "scope": "same_prompt_only",
            "cross_prompt": "deferred_until_after_cutover",
            "cutover_date": CUTOVER_DATE.isoformat(),
            "scanned_files": audit.scanned_files,
            "registry_size": len(AUDIT_PROMPT_REVISIONS),
            "hard": [f.model_dump() for f in hard],
            "soft": [f.model_dump() for f in soft],
            "soft_raw": soft_raw,
            "soft_triaged": soft_triaged,
            "soft_new": soft_new,
            "soft_must_may_triaged": [s.model_dump() for s in sorted(TRIAGED_SOFT_MUST_MAY, key=lambda s: s.prompt_id)],
            "suppressed": [f.model_dump() for f in audit.findings if f.suppressed],
            "noqa_count": noqa_total,
            "noqa_max": NOQA_MAX,
        }
        print(
            f"audit: {len(hard)} hard same-prompt "
            f"(NOT cross-prompt — deferred after cutover {CUTOVER_DATE.isoformat()}); "
            f"soft_raw={soft_raw} soft_triaged={soft_triaged} soft_new={soft_new}; "
            f"noqa={noqa_total}/{NOQA_MAX}; "
            f"registry={len(AUDIT_PROMPT_REVISIONS)} files"
        )
        _print_findings(f"audit hard same-prompt ({len(hard)}):", hard)
        _print_findings(f"audit soft ({len(soft)}):", soft)
        if noqa_total > NOQA_MAX:
            print(f"noqa ceiling FAILED: {noqa_total} > {NOQA_MAX}", file=sys.stderr)
            exit_code = 1
        if args.strict and hard:
            exit_code = 1

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report: {args.report}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
