# src/palatium_ai/application/agents/evals/conflict_linter/fixtures.py

"""Load ``tests/fixtures/conflicts`` manifest + snippets."""

from __future__ import annotations

import json

from pathlib import Path

from palatium_ai.application.agents.evals.conflict_linter.models import ConflictReport, FixtureCase
from palatium_ai.application.agents.evals.conflict_linter.policy import FIXTURE_FLOOR
from palatium_ai.application.agents.evals.conflict_linter.scan import scan_text

_REPO_ROOT = Path(__file__).resolve().parents[6]
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "conflicts"
_MANIFEST = _FIXTURES / "manifest.json"


def load_manifest() -> tuple[FixtureCase, ...]:
    raw = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError(f"conflicts manifest must be a JSON list, got {type(raw).__name__}")
    cases = tuple(FixtureCase.model_validate(item) for item in raw)
    n_conflict = sum(1 for c in cases if c.expected == "conflict")
    n_non = sum(1 for c in cases if c.expected == "non_conflict")
    if n_conflict < FIXTURE_FLOOR or n_non < FIXTURE_FLOOR:
        raise ValueError(
            f"fixture floor is {FIXTURE_FLOOR}+{FIXTURE_FLOOR} (floor, not ceiling); "
            f"got conflict={n_conflict} non_conflict={n_non}"
        )
    return cases


def fixture_text(case: FixtureCase) -> str:
    path = _FIXTURES / case.relative_path
    return path.read_text(encoding="utf-8")


def run_fixture_suite() -> tuple[ConflictReport, dict[str, bool]]:
    """Return aggregate report + per-fixture ``passed`` (expectation matched)."""
    cases = load_manifest()
    findings = []
    results: dict[str, bool] = {}
    for case in cases:
        text = fixture_text(case)
        path = f"tests/fixtures/conflicts/{case.relative_path}"
        hit = scan_text(text, path=path, prompt_id=case.fixture_id)
        active = [item for item in hit if not item.suppressed]
        has_hard = any(item.severity == "hard" for item in active)
        if case.expected == "conflict":
            results[case.fixture_id] = has_hard
        else:
            results[case.fixture_id] = not has_hard
        findings.extend(hit)
    return (
        ConflictReport(findings=tuple(findings), scanned_files=len(cases), mode="same_prompt"),
        results,
    )


def fixture_metrics(results: dict[str, bool], cases: tuple[FixtureCase, ...]) -> dict[str, float]:
    """Recall on conflicts; false-positive rate on non-conflicts."""
    conflict_ids = [c.fixture_id for c in cases if c.expected == "conflict"]
    non_ids = [c.fixture_id for c in cases if c.expected == "non_conflict"]
    recall = sum(1 for fid in conflict_ids if results.get(fid)) / len(conflict_ids) if conflict_ids else 1.0
    fp_rate = sum(1 for fid in non_ids if not results.get(fid)) / len(non_ids) if non_ids else 0.0
    return {"recall": recall, "fp_rate": fp_rate}
