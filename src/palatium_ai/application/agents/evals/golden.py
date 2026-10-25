# src/palatium_ai/application/agents/evals/golden.py

"""Golden manifest: prompt files → agent → eval cases (Phase 6, 075).

The manifest is a *registry*, not a second case list: eval cases stay in
``application/agents/<agent>/evals/tasks.json`` (rule 050 — one owner per fact).
It binds prompt sources to agents so a prompt PR can run exactly the affected
evals instead of a blind full sweep.
"""

from __future__ import annotations

import hashlib
import json

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

import palatium_ai

_MANIFEST_PATH = Path(__file__).resolve().parent / "golden_manifest.json"
_PACKAGE_ROOT = Path(palatium_ai.__file__).resolve().parent
_AGENTS_PREFIX = "application/agents/"
_EVALS_SUFFIX = "/evals/"


class GoldenManifestError(ValueError):
    """Manifest is unreadable, incomplete or drifted from the source tree."""


class GoldenAgentEntry(BaseModel, frozen=True):
    """Prompt sources of one agent (paths relative to ``src/palatium_ai``)."""

    prompts: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_blank_patterns(self) -> GoldenAgentEntry:
        if any(not pattern.strip() for pattern in self.prompts):
            msg = "golden manifest: empty prompts pattern"
            raise GoldenManifestError(msg)
        return self


class GoldenManifest(BaseModel, frozen=True):
    """Versioned registry of prompt sources per agent."""

    version: str = Field(min_length=1)
    agents: Mapping[str, GoldenAgentEntry]

    @model_validator(mode="after")
    def _require_agents(self) -> GoldenManifest:
        if not self.agents:
            msg = "golden manifest: no agents registered"
            raise GoldenManifestError(msg)
        return self

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.agents))


def package_root() -> Path:
    """Directory of the ``palatium_ai`` package (base of manifest-relative paths)."""
    return _PACKAGE_ROOT


def _load_payload(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        msg = f"golden manifest missing: {path.as_posix()}"
        raise GoldenManifestError(msg)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"golden manifest is not valid JSON: {path.as_posix()}"
        raise GoldenManifestError(msg) from exc
    if not isinstance(payload, dict):
        msg = "golden manifest must be a JSON object"
        raise GoldenManifestError(msg)
    return payload


def load_golden_manifest(path: Path | None = None) -> GoldenManifest:
    """Load and validate the golden manifest (fail-closed on drift)."""
    payload = _load_payload(path or _MANIFEST_PATH)
    try:
        return GoldenManifest.model_validate(payload)
    except ValidationError as exc:
        msg = f"golden manifest schema mismatch: {exc}"
        raise GoldenManifestError(msg) from exc


def resolve_prompt_files(
    agent: str,
    manifest: GoldenManifest | None = None,
) -> tuple[Path, ...]:
    """Resolve an agent's prompt globs to existing files (sorted, stable)."""
    registry = manifest or load_golden_manifest()
    entry = registry.agents.get(agent)
    if entry is None:
        msg = f"golden manifest does not register agent: {agent}"
        raise GoldenManifestError(msg)

    files: set[Path] = set()
    for pattern in entry.prompts:
        matched = {path.resolve() for path in _PACKAGE_ROOT.glob(pattern) if path.is_file()}
        if not matched:
            msg = f"golden manifest pattern matched no files for {agent}: {pattern}"
            raise GoldenManifestError(msg)
        files.update(matched)
    return tuple(sorted(files))


def prompt_digest(agent: str, manifest: GoldenManifest | None = None) -> str:
    """sha256 over ``(relative path, bytes)`` of every prompt file of ``agent``.

    Reported in the gate artifact so a reviewer can tell which prompt revision the
    passing score was measured against. It is deliberately not a merge gate: a
    digest gate would demand re-blessing on every intentional prompt edit (050).
    """
    hasher = hashlib.sha256()
    for path in resolve_prompt_files(agent, manifest):
        hasher.update(path.relative_to(_PACKAGE_ROOT).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _package_relative(raw: str) -> str | None:
    """Normalize a changed path to ``src/palatium_ai``-relative POSIX form."""
    text = raw.strip().replace("\\", "/")
    if not text:
        return None
    text = text.removeprefix("./")
    absolute = Path(raw)
    if absolute.is_absolute():
        try:
            return absolute.resolve().relative_to(_PACKAGE_ROOT).as_posix()
        except ValueError:
            return None
    marker = "src/palatium_ai/"
    if marker in text:
        return text.split(marker, 1)[1]
    return text


def agents_for_changed_paths(
    changed_paths: Iterable[str],
    manifest: GoldenManifest | None = None,
) -> tuple[str, ...]:
    """Map changed repository paths to the agents whose evals must run.

    A path affects an agent when it is one of the agent's prompt files or lives
    under ``application/agents/<agent>/evals/``. Everything else is ignored — the
    full suite still runs in ``ci_quality`` for non-prompt changes.
    """
    registry = manifest or load_golden_manifest()
    normalized: set[str] = set()
    for value in map(_package_relative, changed_paths):
        if value:
            normalized.add(value)

    affected: list[str] = []
    for agent in registry.agent_names:
        prompt_paths = {path.relative_to(_PACKAGE_ROOT).as_posix() for path in resolve_prompt_files(agent, registry)}
        evals_prefix = f"{_AGENTS_PREFIX}{agent}{_EVALS_SUFFIX}"
        if prompt_paths & normalized or any(path.startswith(evals_prefix) for path in normalized):
            affected.append(agent)
    return tuple(affected)
