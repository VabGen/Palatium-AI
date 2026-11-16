# tests/unit/test_conflict_linter.py

"""Conflict-linter v1: fixtures gates, noqa hatch, same-prompt audit smoke."""

from __future__ import annotations

from palatium_ai.application.agents.evals.conflict_linter.fixtures import (
    fixture_metrics,
    load_manifest,
    run_fixture_suite,
)
from palatium_ai.application.agents.evals.conflict_linter.judge import HeuristicJudge
from palatium_ai.application.agents.evals.conflict_linter.noqa import parse_noqa_reason
from palatium_ai.application.agents.evals.conflict_linter.scan import scan_audit_revisions, scan_text


def test_fixture_suite_meets_recall_and_fp_gates() -> None:
    from palatium_ai.application.agents.evals.conflict_linter.policy import FIXTURE_FLOOR

    report, results = run_fixture_suite()
    cases = load_manifest()
    metrics = fixture_metrics(results, cases)
    n_conflict = len([c for c in cases if c.expected == "conflict"])
    n_non = len([c for c in cases if c.expected == "non_conflict"])
    assert n_conflict >= FIXTURE_FLOOR
    assert n_non >= FIXTURE_FLOOR
    assert n_non > FIXTURE_FLOOR, "adversarial non-conflicts should grow the floor set"
    assert metrics["recall"] >= 0.8, metrics
    assert metrics["fp_rate"] <= 0.2, (metrics, results)
    assert report.scanned_files == len(cases)


def test_heuristic_judge_recall_on_conflict_fixtures() -> None:
    cases = [c for c in load_manifest() if c.expected == "conflict"]
    judge = HeuristicJudge()
    hits = 0
    for case in cases:
        from palatium_ai.application.agents.evals.conflict_linter.fixtures import fixture_text

        text = fixture_text(case)
        static = scan_text(text, path=case.relative_path, prompt_id=case.fixture_id)
        judged = judge.judge(text, path=case.relative_path, prompt_id=case.fixture_id)
        if any(f.severity == "hard" and not f.suppressed for f in static + judged):
            hits += 1
    assert hits / len(cases) >= 0.8


def test_noqa_suppresses_same_section_antonym() -> None:
    text = """# TASK
Be briefly.
Provide detailed exhaustive answers.
# noqa: conflict-linter — demo hatch for security-style exception
"""
    findings = scan_text(text, path="demo.txt")
    assert findings
    assert all(f.suppressed for f in findings if f.kind == "antonym_pair")


def test_noqa_parse_requires_marker() -> None:
    assert parse_noqa_reason("x = 1  # noqa: conflict-linter — fence never-follow") == "fence never-follow"
    assert parse_noqa_reason("x = 1") is None


def test_audit_revisions_scan_runs() -> None:
    """Smoke: scanner completes on real AUDIT_PROMPT_REVISIONS (triage, not zero-hard DoD)."""
    report = scan_audit_revisions()
    assert report.scanned_files >= 13
    assert report.mode == "same_prompt"
