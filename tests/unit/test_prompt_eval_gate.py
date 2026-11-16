# tests/unit/test_prompt_eval_gate.py

"""Prompt-change eval gate: manifest registry + affected-agent mapping (Phase 6, 075)."""

from __future__ import annotations

import hashlib
import json

from pathlib import Path

import pytest

from palatium_ai.application.agents.evals import golden
from palatium_ai.application.agents.evals.golden import (
    GoldenManifestError,
    agents_for_changed_paths,
    load_golden_manifest,
    prompt_digest,
    resolve_prompt_files,
)
from palatium_ai.application.agents.evals.prompt_gate import prompt_file_count, run_prompt_gate
from palatium_ai.application.agents.evals.runner import AGENT_PACKAGES


def test_manifest_registers_every_agent_with_evals() -> None:
    manifest = load_golden_manifest()
    assert set(manifest.agent_names) == set(AGENT_PACKAGES)


@pytest.mark.parametrize("agent", AGENT_PACKAGES)
def test_every_agent_prompt_glob_resolves(agent: str) -> None:
    files = resolve_prompt_files(agent)
    assert files, f"{agent} registered no prompt files"
    assert all(path.is_file() for path in files)


def test_multi_file_prompts_are_registered() -> None:
    # context_enricher keeps prompts per sub-agent (continuation/weaving): a single
    # prompts.py pattern would silently miss half of the agent (055).
    files = resolve_prompt_files("context_enricher")
    assert len(files) >= 2


def test_prompt_digest_matches_manual_sha256() -> None:
    prompt_file = resolve_prompt_files("critic")[0]
    relative = prompt_file.relative_to(golden.package_root()).as_posix()
    expected = hashlib.sha256()
    expected.update(relative.encode("utf-8"))
    expected.update(b"\0")
    expected.update(prompt_file.read_bytes())
    expected.update(b"\0")
    assert prompt_digest("critic") == expected.hexdigest()


def test_prompt_digest_is_stable_across_calls() -> None:
    assert prompt_digest("critic") == prompt_digest("critic")


def test_prompt_digests_differ_between_agents() -> None:
    digests = {agent: prompt_digest(agent) for agent in AGENT_PACKAGES}
    assert len(set(digests.values())) == len(digests)


def test_unknown_agent_digest_fails_closed() -> None:
    with pytest.raises(GoldenManifestError, match="does not register agent"):
        prompt_digest("not_an_agent")


def test_manifest_pattern_without_files_fails_closed(tmp_path: Path) -> None:
    manifest_file = tmp_path / "golden_manifest.json"
    manifest_file.write_text(
        json.dumps({"version": "test", "agents": {"critic": {"prompts": ["application/agents/critic/missing*.py"]}}}),
        encoding="utf-8",
    )
    manifest = load_golden_manifest(manifest_file)
    with pytest.raises(GoldenManifestError, match="matched no files"):
        resolve_prompt_files("critic", manifest)


def test_empty_manifest_fails_closed(tmp_path: Path) -> None:
    manifest_file = tmp_path / "golden_manifest.json"
    manifest_file.write_text(json.dumps({"version": "test", "agents": {}}), encoding="utf-8")
    with pytest.raises(GoldenManifestError, match="no agents"):
        load_golden_manifest(manifest_file)


@pytest.mark.parametrize(
    "changed,expected",
    (
        ("src/palatium_ai/application/agents/critic/prompts.py", ("critic",)),
        ("application/agents/critic/prompts.py", ("critic",)),
        ("src\\palatium_ai\\application\\agents\\critic\\prompts.py", ("critic",)),
        ("src/palatium_ai/application/agents/context_enricher/weaving/prompts.py", ("context_enricher",)),
        ("src/palatium_ai/application/agents/formatter/evals/tasks.json", ("formatter",)),
        ("src/palatium_ai/domain/policies/types.py", ()),
        ("docs/README.md", ()),
    ),
)
def test_agents_for_changed_paths(changed: str, expected: tuple[str, ...]) -> None:
    assert agents_for_changed_paths([changed]) == expected


def test_agents_for_changed_paths_deduplicates() -> None:
    changed = [
        "src/palatium_ai/application/agents/critic/prompts.py",
        "src/palatium_ai/application/agents/critic/evals/tasks.json",
    ]
    assert agents_for_changed_paths(changed) == ("critic",)


def test_prompt_file_count_covers_manifest() -> None:
    assert prompt_file_count() >= len(AGENT_PACKAGES)


@pytest.mark.asyncio()
async def test_gate_without_affected_agents_is_explicitly_empty() -> None:
    result = await run_prompt_gate(["docs/README.md"])
    assert result.passed is True
    assert result.affected_agents == ()
    assert result.reports == ()
    assert result.digests == ()


@pytest.mark.asyncio()
async def test_gate_runs_affected_agent_evals() -> None:
    result = await run_prompt_gate(["src/palatium_ai/application/agents/critic/prompts.py"])
    assert result.affected_agents == ("critic",)
    assert len(result.reports) == 1
    assert result.reports[0].agent == "critic"
    assert result.passed is True, result.failures
    assert result.digests[0].agent == "critic"


@pytest.mark.asyncio()
async def test_gate_result_serializes() -> None:
    result = await run_prompt_gate(["src/palatium_ai/application/agents/critic/prompts.py"])
    payload = json.loads(result.model_dump_json())
    assert payload["golden_version"]
    assert payload["affected_agents"] == ["critic"]
    assert payload["passed"] is True
