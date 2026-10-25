# tests/unit/test_prompt_evals_workflow.py

"""prompt-evals workflow contract: triggers, pins, secret gate (Phase 6, 025/075)."""

from __future__ import annotations

import re
import tomllib

from pathlib import Path
from typing import Any

import yaml

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "prompt-evals.yml"
_SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
_GATE_SCRIPT = "scripts/run_prompt_eval_gate.py"


def _workflow() -> dict[str, Any]:
    payload = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def test_workflow_exists() -> None:
    assert _WORKFLOW.is_file()


def test_triggers_on_prompt_and_eval_paths() -> None:
    # YAML 1.1 parses the bare `on:` key as boolean True; accept both spellings.
    triggers = _workflow().get("on") or _workflow().get(True)
    assert isinstance(triggers, dict)
    paths = [str(item) for item in triggers["pull_request"]["paths"]]
    assert "src/palatium_ai/application/agents/**/prompts.py" in paths
    assert any(path.endswith("/evals/**") for path in paths)


def test_all_actions_are_sha_pinned() -> None:
    workflow = _workflow()
    for job in workflow["jobs"].values():
        for step in _steps(job):
            uses = step.get("uses")
            if isinstance(uses, str):
                assert _SHA_PIN.search(uses), f"unpinned action: {uses}"


def test_deterministic_job_runs_the_gate() -> None:
    steps = _steps(_workflow()["jobs"]["deterministic"])
    commands = [str(step.get("run", "")) for step in steps]
    assert any(_GATE_SCRIPT in command for command in commands)
    gate = next(command for command in commands if _GATE_SCRIPT in command)
    assert "--base-ref" in gate
    assert "--metrics" not in gate


def test_deepeval_job_is_secret_gated_and_pinned() -> None:
    job = _workflow()["jobs"]["deepeval"]
    assert job["needs"] == "deterministic"
    steps = _steps(job)
    step_ids = {step.get("id") for step in steps}
    assert "judge" in step_ids

    gated = [
        " ".join(filter(None, (str(step.get("name", "")), str(step.get("run", "")))))
        for step in steps
        if "steps.judge.outputs.available == 'true'" in str(step.get("if", ""))
    ]
    assert any("deepeval==" in text for text in gated)
    assert any("--metrics deepeval" in text for text in gated)


def test_deepeval_is_not_part_of_the_project_lockfile() -> None:
    # deepeval pins rich<15, which would downgrade the production fastmcp dependency
    # (025/055): it must stay an eval-only install, never a pyproject group.
    root = _WORKFLOW.parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(project["project"].get("dependencies", []))
    for requirements in project.get("dependency-groups", {}).values():
        declared.extend(str(item) for item in requirements if isinstance(item, str))
    for requirements in project["project"].get("optional-dependencies", {}).values():
        declared.extend(str(item) for item in requirements)
    assert not any(requirement.lower().startswith("deepeval") for requirement in declared)
    version = _workflow()["env"]["DEEPEVAL_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
