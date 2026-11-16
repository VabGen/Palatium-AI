"""CI contract: the red-team nightly exists and cannot be quietly removed (082, 075, 020).

Red-team is a gate, not a habit: without a scheduled job, `tests/redteam` would only run
when someone remembered, and the corpus would rot into green. This pins the wiring:

* the workflow exists, is scheduled and manually runnable;
* it runs exactly the corpus suite under the `slow` marker (the selection PR CI excludes);
* every action is SHA-pinned — a nightly is still supply chain (025);
* the corpus keeps negative controls, so "refuse everything" cannot look healthy.
"""

from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "redteam-nightly.yml"
CORPUS = REPO_ROOT / "tests" / "redteam" / "corpus.jsonl"
_SHA_REF = re.compile(r"@[0-9a-f]{40}\b")


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "redteam-nightly.yml must parse to a mapping"
    return loaded


def test_nightly_exists_and_is_scheduled() -> None:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    triggers = _workflow().get("on", _workflow().get(True))
    assert isinstance(triggers, dict), "workflow must declare triggers"
    assert "schedule" in triggers, "red-team must run on a schedule, not only on demand"
    assert "workflow_dispatch" in triggers, "a failed nightly must be re-runnable by hand"


def test_nightly_runs_the_corpus_suite() -> None:
    jobs: dict[str, Any] = _workflow()["jobs"]
    runs = [step.get("run", "") for job in jobs.values() for step in job.get("steps", []) if isinstance(step, dict)]
    assert any("pytest tests/redteam" in command for command in runs), "job must run the corpus"
    assert any("-m slow" in command for command in runs), "corpus runs under the `slow` marker"


def test_every_action_is_sha_pinned() -> None:
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- uses:") and not stripped.startswith("uses:"):
            continue
        target = stripped.split("uses:", 1)[1].strip()
        assert _SHA_REF.search(target), f"action is not SHA-pinned: {target}"


def test_corpus_keeps_negative_controls() -> None:
    cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(cases) >= 10, "a red-team corpus of a handful of rows proves nothing"
    expectations = {case["expect"] for case in cases}
    assert "allow" in expectations or "allowed" in expectations, "no negative control: a gate that refuses everything would pass"
