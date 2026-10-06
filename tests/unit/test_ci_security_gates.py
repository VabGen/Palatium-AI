"""Supply-chain gates must be able to *fail* (025, 075, 050).

A gate that cannot fail is not a gate. ``scripts/ci_security.py`` enforces two rules that
would otherwise live only in prose: the lockfile must match ``pyproject.toml``, and every
third-party GitHub Action must be pinned to a commit SHA with a version comment.

The negative cases are pinned here because the failure mode is silent: if the pin scanner
stops recognising a mutable tag, CI stays green while upstream can change the code we
execute in this repository without a pull request.
"""

from __future__ import annotations

import importlib.util
import sys

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ci_security.py"

_PINNED = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"


def _load_module():
    """Import ``scripts/ci_security.py`` without making ``scripts`` a package."""
    spec = importlib.util.spec_from_file_location("ci_security_under_test", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_security_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _scan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, yaml_body: str) -> list[str]:
    """Run the pin scanner against a synthetic workflows directory."""
    module = _load_module()
    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    (workflows / "ci.yml").write_text(yaml_body, encoding="utf-8")
    # `_ROOT` is only used to render a readable path, so the scan can run anywhere.
    monkeypatch.setattr(module, "_ROOT", tmp_path)
    monkeypatch.setattr(module, "_WORKFLOWS", workflows)
    return module.unpinned_actions()


@pytest.mark.parametrize(
    "line",
    (
        "actions/checkout@v4",  # moving major tag
        "actions/checkout@main",  # moving branch
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",  # SHA, no version comment
        "actions/checkout@11D5960A326750D5838078E36CF38B85AF677262 # v4.4.0",  # not the canonical form
    ),
)
def test_mutable_or_unversioned_refs_are_flagged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str) -> None:
    """Anything that is not `<40-hex sha> # vX.Y.Z` must be reported."""
    body = f"jobs:\n  build:\n    steps:\n      - uses: {line}\n"

    offenders = _scan(monkeypatch, tmp_path, body)

    assert len(offenders) == 1, offenders
    assert "ci.yml:4" in offenders[0]


def test_pinned_and_local_actions_are_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A SHA-pinned upstream action and a local composite action are both fine."""
    body = (
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        f"      - uses: {_PINNED}\n"
        "        with:\n"
        "          fetch-depth: 0\n"
        "      - uses: ./.github/actions/setup\n"
    )

    assert _scan(monkeypatch, tmp_path, body) == []


def test_repository_workflows_are_fully_pinned() -> None:
    """The real workflows are the artefact the gate protects; drift fails here first."""
    module = _load_module()

    assert module.unpinned_actions() == []


def test_triage_allowlist_only_returns_advisory_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Comments and blank lines in the triage file must not become ignored advisories."""
    triage = tmp_path / "pip-audit-ignore.txt"
    triage.write_text(
        "# comment\n\nGHSA-0000-0000-0000  # reason; PAL-1; review 2026-12-01\nCVE-2026-1111\n",
        encoding="utf-8",
    )
    module = _load_module()
    monkeypatch.setattr(module, "_IGNORE_FILE", triage)

    assert module._load_ignored_vulns() == ["GHSA-0000-0000-0000", "CVE-2026-1111"]


def _dockerfile(tmp_path: Path, body: str, name: str = "Dockerfile") -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_mutable_base_image_tag_is_flagged(tmp_path: Path) -> None:
    """The tag is a moving target: the same build can produce a different image tomorrow."""
    _dockerfile(tmp_path, "FROM python:3.14-slim AS base\n")

    offenders = _load_module().unpinned_base_images(tmp_path)

    assert offenders == ["Dockerfile:1: python:3.14-slim"]


_PINNED_FROM = "FROM python:3.14-slim@sha256:" + "c" * 64 + " AS base"


@pytest.mark.parametrize(
    "line",
    (
        "FROM python:3.14-slim@sha256:" + "a" * 64 + " AS second",
        "FROM python:${PYTHON_VERSION}-slim@sha256:" + "b" * 64 + " AS third",
        "FROM base AS deps",  # build stage: nothing upstream to pin
        "FROM base AS runtime",
        "FROM scratch AS empty",  # empty base by definition
    ),
)
def test_pinned_and_internal_bases_are_accepted(tmp_path: Path, line: str) -> None:
    """Digest pins (with or without ARG interpolation) and stage refs must stay green."""
    _dockerfile(tmp_path, f"{_PINNED_FROM}\n{line}\nFROM base AS final\n")

    assert _load_module().unpinned_base_images(tmp_path) == []


def test_fully_parameterised_base_image_is_flagged(tmp_path: Path) -> None:
    """`FROM ${BASE_IMAGE}` cannot be verified, so it is reported instead of trusted."""
    _dockerfile(tmp_path, "FROM ${BASE_IMAGE} AS runtime\n")

    offenders = _load_module().unpinned_base_images(tmp_path)

    assert len(offenders) == 1
    assert "${BASE_IMAGE}" in offenders[0]


def test_vendored_dockerfiles_are_not_our_debt(tmp_path: Path) -> None:
    """Another team's Dockerfile is out of scope (017, 090) — reporting it would only add noise."""
    vendor = tmp_path / "mcp_servers" / "edms" / "edms-ai-assistant" / "docker"
    vendor.mkdir(parents=True)
    (vendor / "Dockerfile").write_text("FROM python:3.14 AS builder\n", encoding="utf-8")

    assert _load_module().unpinned_base_images(tmp_path) == []


def test_repository_dockerfiles_are_digest_pinned() -> None:
    """The artefact the gate protects: a green run must reflect the real Dockerfiles."""
    assert _load_module().unpinned_base_images() == []
