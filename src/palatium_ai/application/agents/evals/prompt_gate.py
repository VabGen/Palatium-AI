# src/palatium_ai/application/agents/evals/prompt_gate.py

"""Prompt-change eval gate (Phase 6, 075).

Turns "this prompt changed" into "these evals must still pass the baseline".
Reuses the existing runner and baseline comparison — no second threshold logic.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from palatium_ai.application.agents.evals import golden
from palatium_ai.application.agents.evals.report import AgentEvalReport
from palatium_ai.application.agents.evals.runner import assert_baseline_gate, run_agent_evals

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class PromptDigest(BaseModel, frozen=True):
    """Measured prompt revision of one agent (artifact, not a gate)."""

    agent: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class PromptGateResult(BaseModel, frozen=True):
    """Outcome of the prompt-change gate; ``failures`` empty means pass."""

    golden_version: str = Field(min_length=1)
    changed_paths: tuple[str, ...] = ()
    affected_agents: tuple[str, ...] = ()
    digests: tuple[PromptDigest, ...] = ()
    reports: tuple[AgentEvalReport, ...] = ()
    failures: tuple[str, ...] = ()
    #: Explicit field (not a property): the gate outcome is part of the serialized
    #: artifact, and mypy does not support decorators stacked on ``property``.
    passed: bool


def affected_agents(changed_paths: Sequence[str]) -> tuple[str, ...]:
    """Agents whose evals a changed-path set touches."""
    return golden.agents_for_changed_paths(changed_paths)


def _collect_failures(reports: Sequence[AgentEvalReport]) -> tuple[str, ...]:
    if not reports:
        return ()
    failures: list[str] = []
    for report in reports:
        if report.passed != report.total:
            failures.extend(f"{report.agent}/{detail}" for detail in report.details)
    try:
        assert_baseline_gate({report.agent: report for report in reports})
    except AssertionError as exc:
        failures.append(f"baseline gate: {exc}")
    return tuple(failures)


async def run_prompt_gate(changed_paths: Sequence[str]) -> PromptGateResult:
    """Run the deterministic evals of every agent affected by ``changed_paths``.

    No affected agent means no eval run: the artifact still records the empty
    ``affected_agents`` so the skip is visible, never implied (055).
    """
    manifest = golden.load_golden_manifest()
    agents = golden.agents_for_changed_paths(changed_paths, manifest=manifest)
    reports_list = [await run_agent_evals(agent) for agent in agents]
    reports = tuple(reports_list)
    digests = tuple(PromptDigest(agent=agent, sha256=golden.prompt_digest(agent, manifest)) for agent in agents)
    failures = _collect_failures(reports)
    return PromptGateResult(
        golden_version=manifest.version,
        changed_paths=tuple(changed_paths),
        affected_agents=agents,
        digests=digests,
        reports=reports,
        failures=failures,
        passed=not failures,
    )


def prompt_file_count() -> int:
    """Total prompt files registered in the golden manifest (drift smoke check)."""
    manifest = golden.load_golden_manifest()
    return sum(len(golden.resolve_prompt_files(agent, manifest)) for agent in manifest.agent_names)
