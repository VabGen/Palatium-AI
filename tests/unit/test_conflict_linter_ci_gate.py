# tests/unit/test_conflict_linter_ci_gate.py

"""§2 CI pin: conflict-linter workflow + cutover calendar (A1-scoped, no CTCO closures).

Keep this file free of LLM-controls / Anthropic-smoke pins so the conflict-linter
PR can land without pulling prompt-audit §1 closures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFLICT_LINTER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "conflict-linter.yml"


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
    from datetime import date

    from palatium_ai.application.agents.evals.conflict_linter.policy import (
        CUTOVER_DATE,
        continue_on_error_required,
    )

    day = date.fromisoformat(as_of)
    assert continue_on_error_required(as_of=day) is expect_continue_on_error
    assert (day < CUTOVER_DATE) is expect_continue_on_error


def test_conflict_linter_job_exists() -> None:
    """§2 DoD: workflow matches continue_on_error_required() for *today*; fixtures non-empty."""
    from palatium_ai.application.agents.evals.conflict_linter.fixtures import load_manifest
    from palatium_ai.application.agents.evals.conflict_linter.noqa import count_noqa_markers
    from palatium_ai.application.agents.evals.conflict_linter.policy import (
        CUTOVER_DATE,
        NOQA_MAX,
        continue_on_error_required,
    )
    from palatium_ai.application.agents.evals.prompt_revisions import AUDIT_PROMPT_REVISIONS

    assert CONFLICT_LINTER_WORKFLOW.is_file(), "conflict-linter.yml missing — plans/prompt-audit-backlog-2026.md §2"
    text = CONFLICT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    assert CUTOVER_DATE.isoformat() in text, "workflow must mention cutover date from policy.CUTOVER_DATE"
    loaded = cast("dict[str, Any]", yaml.safe_load(text))
    jobs = loaded.get("jobs", {})
    assert "conflict-linter" in jobs, "job id conflict-linter must exist"
    job = jobs["conflict-linter"]
    if continue_on_error_required():
        assert job.get("continue-on-error") is True, (
            f"before {CUTOVER_DATE.isoformat()} job must stay non-blocking (continue-on-error: true)"
        )
    else:
        assert job.get("continue-on-error") in (False, None), (
            f"on/after {CUTOVER_DATE.isoformat()} remove continue-on-error (blocking cutover)"
        )
    commands = [str(step["run"]) for step in job.get("steps", []) if isinstance(step, dict) and "run" in step]
    assert any("run_conflict_linter.py" in cmd for cmd in commands)

    cases = load_manifest()
    assert cases, "conflict fixtures manifest must be non-empty"

    noqa_total = 0
    src = REPO_ROOT / "src" / "palatium_ai"
    for revision in AUDIT_PROMPT_REVISIONS:
        noqa_total += count_noqa_markers((src / revision.relative_path).read_text(encoding="utf-8"))
    assert noqa_total <= NOQA_MAX, f"noqa escape hatch ceiling {NOQA_MAX} exceeded ({noqa_total}) — review or fix prompts"
    assert len(AUDIT_PROMPT_REVISIONS) == 15, "AUDIT_PROMPT_REVISIONS size drift — update plan §2 registry note if intentional"
