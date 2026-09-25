#!/usr/bin/env python
"""Cross-platform CI quality baseline.

Gates (in order):
  1. ruff        — lint + security selectors (``S``), whole repo (matches ``tox -e lint``).
  2. ruff format — formatting drift check (pyproject: ``ruff format .``).
  3. layers      — hexagonal import contract from rule 000 (``scripts/check_import_layers.py``).
  4. mypy        — ``--strict`` on the platform package.
  5. pytest      — FULL ``tests/`` suite (not a hand-maintained file list) + coverage.
  6. coverage    — ``domain/policies`` >= 90% (docs/max-pro-level-tz.md §13/§15).
  7. SLA math    — budget gate arithmetic.
  8. agent evals — deterministic baseline.
  9. PyJWT       — conflict guard (``jwt`` must not shadow ``PyJWT``).

SCA (pip-audit) lives in ``scripts/ci_security.py`` — separate CI job, separate concern.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from importlib import metadata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ARTIFACTS = _ROOT / "artifacts"
_COVERAGE_JSON = _ARTIFACTS / "coverage.json"

# docs/max-pro-level-tz.md §13 + §15: "Coverage domain/policies >= 90%".
_POLICIES_COVERAGE_TARGET = float(os.environ.get("PALATIUM_COV_MIN_POLICIES", "90"))
# Global floor is a ratchet: unset → measured & reported, then pinned by the team.
_GLOBAL_COVERAGE_TARGET = os.environ.get("PALATIUM_COV_MIN_GLOBAL", "").strip()
_POLICIES_PATH_FRAGMENT = "/domain/policies/"
# An async test without @pytest.mark.asyncio would be silently not-run under strict mode.
_PYTEST_MARKER_EXPR = "not live and not llm_live"


def _run(title: str, argv: list[str]) -> None:
    print(f"== {title} ==")
    completed = subprocess.run(argv, cwd=_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _assert_pyjwt_not_shadowed() -> None:
    print("== conflict check: jwt vs PyJWT ==")
    names = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
    if "jwt" in names and "pyjwt" in names:
        raise SystemExit(
            "Conflicting package 'jwt' is installed alongside PyJWT. "
            "Remove it (`poetry remove jwt` then `poetry sync`). Use PyJWT only."
        )
    from jwt import PyJWKClient  # noqa: F401

    print("PyJWT import OK")


def _coverage_summary() -> tuple[float, float]:
    """Return ``(global_percent, policies_percent)`` from the pytest-cov JSON report."""
    if not _COVERAGE_JSON.exists():
        raise SystemExit(f"Coverage report missing: {_COVERAGE_JSON.relative_to(_ROOT).as_posix()}")
    data = json.loads(_COVERAGE_JSON.read_text(encoding="utf-8"))
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise SystemExit("Coverage report has unexpected shape (no 'files' mapping)")

    global_statements = global_covered = 0
    policies_statements = policies_covered = 0
    for raw_path, entry in files.items():
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary", {})
        statements = int(summary.get("num_statements", 0))
        covered = int(summary.get("covered_lines", 0))
        global_statements += statements
        global_covered += covered
        # Path-shape agnostic (absolute vs relative, POSIX vs Windows separators).
        if _POLICIES_PATH_FRAGMENT in Path(raw_path).as_posix():
            policies_statements += statements
            policies_covered += covered

    if global_statements == 0:
        raise SystemExit("Coverage report contains no statements — check --cov scope")
    if policies_statements == 0:
        raise SystemExit("Coverage report contains no domain/policies files — check --cov scope")
    return (
        100.0 * global_covered / global_statements,
        100.0 * policies_covered / policies_statements,
    )


def _enforce_coverage() -> None:
    global_percent, policies_percent = _coverage_summary()
    print(f"coverage: global={global_percent:.2f}%  domain/policies={policies_percent:.2f}%")

    if policies_percent < _POLICIES_COVERAGE_TARGET:
        raise SystemExit(
            f"domain/policies coverage {policies_percent:.2f}% < "
            f"{_POLICIES_COVERAGE_TARGET:g}% (docs/max-pro-level-tz.md §13, §15)"
        )

    if _GLOBAL_COVERAGE_TARGET:
        floor = float(_GLOBAL_COVERAGE_TARGET)
        if global_percent < floor:
            raise SystemExit(f"global coverage {global_percent:.2f}% < {floor:g}% (PALATIUM_COV_MIN_GLOBAL)")
        print(f"coverage: global floor {floor:g}% satisfied")
    else:
        print(
            f"coverage: global floor not enforced (set PALATIUM_COV_MIN_GLOBAL to ratchet above {global_percent:.2f}%)"
        )


def main() -> int:
    """Run lint, typing, full test suite + coverage gates, SLA math and agent evals."""
    # Whole repo, matching `tox -e lint`. Linting only src/scripts/tests would let
    # mcp_servers/ (shipped code, see mcp_servers/Dockerfile) drift out of the gate.
    _run("ruff check", ["poetry", "run", "ruff", "check", "."])
    # Formatting is part of the standard (pyproject: "poetry run ruff format .").
    # Enforced so it cannot silently drift between waves.
    _run("ruff format --check", ["poetry", "run", "ruff", "format", "--check", "."])
    # Rule 000: application/ must not import infrastructure/, core/ imports nothing, etc.
    # Standalone checker instead of import-linter — see scripts/check_import_layers.py.
    _run("import layers (000)", ["poetry", "run", "python", "scripts/check_import_layers.py"])
    _run(
        "mypy --strict (src/palatium_ai)",
        [
            "poetry",
            "run",
            "mypy",
            "--strict",
            "src/palatium_ai",
        ],
    )

    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    coverage_report = _COVERAGE_JSON.relative_to(_ROOT).as_posix()
    _run(
        "pytest (full tests/ + coverage)",
        [
            "poetry",
            "run",
            "pytest",
            "tests",
            "-q",
            "-m",
            _PYTEST_MARKER_EXPR,
            "--cov=palatium_ai",
            "--cov-report=term-missing",
            f"--cov-report=json:{coverage_report}",
        ],
    )
    _enforce_coverage()

    _run("SLA math gate", ["poetry", "run", "python", "scripts/run_sla_gates.py", "--check-math"])
    _run("agent evals baseline", ["poetry", "run", "python", "scripts/run_agent_evals.py"])
    # Live --load-health (incl. concurrency=1000) is ops/staging only — not PR CI.
    _assert_pyjwt_not_shadowed()
    print("ci_quality: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
