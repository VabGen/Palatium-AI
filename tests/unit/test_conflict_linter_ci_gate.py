# tests/unit/test_conflict_linter_ci_gate.py

"""§2 CI pin: conflict-linter workflow + cutover calendar (both flags).

Cutover 2026-12-19 = remove continue-on-error AND add --strict on the same
audit step. One without the other is not cutover.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFLICT_LINTER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "conflict-linter.yml"

_POST_CUTOVER_JOB: dict[str, Any] = {
    "runs-on": "ubuntu-latest",
    "steps": [
        {
            "name": "Conflict-linter (fixtures + audit report)",
            "run": (
                "uv run python scripts/run_conflict_linter.py "
                "--fixtures --audit --judge heuristic --strict "
                "--report artifacts/conflict_linter.json"
            ),
        }
    ],
}

_HALF_CUTOVER_JOB: dict[str, Any] = {
    "runs-on": "ubuntu-latest",
    # continue-on-error removed, but --strict missing → incomplete cutover
    "steps": [
        {
            "name": "Conflict-linter (fixtures + audit report)",
            "run": (
                "uv run python scripts/run_conflict_linter.py "
                "--fixtures --audit --judge heuristic "
                "--report artifacts/conflict_linter.json"
            ),
        }
    ],
}


def _audit_step_run(job: dict[str, Any]) -> str:
    commands = [str(step["run"]) for step in job.get("steps", []) if isinstance(step, dict) and "run" in step]
    matches = [cmd for cmd in commands if "run_conflict_linter.py" in cmd]
    assert len(matches) == 1, "exactly one audit step must invoke run_conflict_linter.py"
    return matches[0]


def assert_workflow_matches_cutover(job: dict[str, Any], *, as_of: date) -> None:
    """Both cutover flags must agree with ``continue_on_error_required(as_of=)``."""
    from palatium_ai.application.agents.evals.conflict_linter.policy import (
        continue_on_error_required,
    )

    run = _audit_step_run(job)
    if continue_on_error_required(as_of=as_of):
        assert job.get("continue-on-error") is True, "pre-cutover job must set continue-on-error: true"
        assert "--strict" not in run, "pre-cutover audit step must not pass --strict"
    else:
        assert job.get("continue-on-error") in (False, None), "post-cutover job must remove continue-on-error (blocking)"
        assert "--strict" in run, "post-cutover audit step must pass --strict on the same run"


@pytest.mark.parametrize(
    "as_of,expect_continue_on_error",
    (
        ("2026-12-18", True),
        ("2026-12-19", False),
        ("2026-12-20", False),
    ),
)
def test_cutover_continue_on_error_calendar_contract(
    as_of: str,
    expect_continue_on_error: bool,
) -> None:
    """Pure calendar pin — does not use datetime.now(); both sides of CUTOVER_DATE."""
    from palatium_ai.application.agents.evals.conflict_linter.policy import (
        CUTOVER_DATE,
        continue_on_error_required,
    )

    day = date.fromisoformat(as_of)
    assert continue_on_error_required(as_of=day) is expect_continue_on_error
    assert (day < CUTOVER_DATE) is expect_continue_on_error


@pytest.mark.parametrize(
    "as_of,job_fixture",
    (
        ("2026-12-18", "live"),
        ("2026-12-19", "post"),
        ("2026-12-20", "post"),
    ),
)
def test_cutover_workflow_both_flags(as_of: str, job_fixture: str) -> None:
    """18 Dec → live pre-cutover YAML; 19/20 → canonical post-cutover job shape."""
    if job_fixture == "live":
        loaded = cast("dict[str, Any]", yaml.safe_load(CONFLICT_LINTER_WORKFLOW.read_text(encoding="utf-8")))
        job = loaded["jobs"]["conflict-linter"]
    else:
        job = _POST_CUTOVER_JOB
    assert_workflow_matches_cutover(job, as_of=date.fromisoformat(as_of))


def test_cutover_requires_both_flags() -> None:
    """Removing only continue-on-error (no --strict) must fail the post-cutover contract."""
    with pytest.raises(AssertionError, match="--strict"):
        assert_workflow_matches_cutover(_HALF_CUTOVER_JOB, as_of=date(2026, 12, 19))


def test_conflict_linter_job_exists() -> None:
    """§2 DoD: live workflow matches cutover contract for *today*; fixtures non-empty."""
    from datetime import UTC, datetime

    from palatium_ai.application.agents.evals.conflict_linter.fixtures import load_manifest
    from palatium_ai.application.agents.evals.conflict_linter.noqa import count_noqa_markers
    from palatium_ai.application.agents.evals.conflict_linter.policy import (
        CUTOVER_DATE,
        NOQA_MAX,
    )
    from palatium_ai.application.agents.evals.prompt_revisions import AUDIT_PROMPT_REVISIONS

    assert CONFLICT_LINTER_WORKFLOW.is_file(), "conflict-linter.yml missing — plans/prompt-audit-backlog-2026.md §2"
    text = CONFLICT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    assert CUTOVER_DATE.isoformat() in text, "workflow must mention cutover date from policy.CUTOVER_DATE"
    flat = text.replace("\n", " ")
    assert "continue-on-error AND" in flat, "workflow must document cutover = remove continue-on-error AND add --strict"
    assert "--strict" in flat, "workflow must document cutover = remove continue-on-error AND add --strict"
    loaded = cast("dict[str, Any]", yaml.safe_load(text))
    jobs = loaded.get("jobs", {})
    assert "conflict-linter" in jobs, "job id conflict-linter must exist"
    assert_workflow_matches_cutover(jobs["conflict-linter"], as_of=datetime.now(UTC).date())

    cases = load_manifest()
    assert cases, "conflict fixtures manifest must be non-empty"

    noqa_total = 0
    src = REPO_ROOT / "src" / "palatium_ai"
    for revision in AUDIT_PROMPT_REVISIONS:
        noqa_total += count_noqa_markers((src / revision.relative_path).read_text(encoding="utf-8"))
    assert noqa_total <= NOQA_MAX, f"noqa escape hatch ceiling {NOQA_MAX} exceeded ({noqa_total}) — review or fix prompts"
    assert len(AUDIT_PROMPT_REVISIONS) == 15, "AUDIT_PROMPT_REVISIONS size drift — update plan §2 registry note if intentional"
