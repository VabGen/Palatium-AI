# tests/unit/test_conflict_linter_soft_metric.py

"""§2 Block C: soft_raw / soft_triaged / soft_new (exact signature match)."""

from __future__ import annotations

import json
import subprocess

from pathlib import Path

from palatium_ai.application.agents.evals.conflict_linter.models import ConflictFinding
from palatium_ai.application.agents.evals.conflict_linter.policy import (
    TRIAGED_SOFT_MUST_MAY,
    is_triaged_soft,
    soft_metric_breakdown,
)

_REPO = Path(__file__).resolve().parents[2]
_REPORT = _REPO / "artifacts" / "conflict_linter_soft_metric_test.json"


def test_triage_signature_is_exact_prompt_id_and_kind() -> None:
    assert is_triaged_soft(prompt_id="contextualizer.system", kind="must_may")
    assert not is_triaged_soft(prompt_id="contextualizer.system", kind="always_never")
    assert not is_triaged_soft(prompt_id="contextualizer", kind="must_may")  # substring ≠ match
    assert not is_triaged_soft(prompt_id="formatter.system", kind="must_may")
    assert len(TRIAGED_SOFT_MUST_MAY) == 4


def test_soft_metric_breakdown_subtracts_only_signatures() -> None:
    soft = [
        ConflictFinding(
            path="a.py",
            prompt_id="contextualizer.system",
            severity="soft",
            kind="must_may",
            section="RULES",
            message="must vs may",
            left="MUST",
            right="may",
        ),
        ConflictFinding(
            path="b.py",
            prompt_id="formatter.system",
            severity="soft",
            kind="must_may",
            section="RULES",
            message="must vs may",
            left="must",
            right="may",
        ),
        ConflictFinding(
            path="c.py",
            prompt_id="contextualizer.system",
            severity="soft",
            kind="always_never",
            section="RULES",
            message="always vs never",
            left="always",
            right="never",
        ),
    ]
    raw, triaged, new = soft_metric_breakdown(soft)
    assert raw == 3
    assert triaged == 1
    assert new == 2
    assert new == raw - triaged


def test_audit_report_exposes_soft_metric_fields() -> None:
    """CLI audit JSON must carry soft_raw / soft_triaged / soft_new with identity."""
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(_REPO / "scripts" / "run_conflict_linter.py"),
            "--audit",
            "--judge",
            "none",
            "--report",
            str(_REPORT),
        ],
        cwd=_REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(_REPORT.read_text(encoding="utf-8"))
    audit = payload["audit"]
    assert "soft_raw" in audit and "soft_triaged" in audit and "soft_new" in audit
    assert audit["soft_new"] == audit["soft_raw"] - audit["soft_triaged"]
    assert audit["soft_raw"] >= audit["soft_triaged"]
    # Current registry: four triaged must/may, soft_new should be 0 if only those fire.
    assert audit["soft_triaged"] == 4
    assert audit["soft_new"] == 0
