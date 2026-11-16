"""CI contract: prompt-audit closures + LLM dials stay on the PR path (075, 082).

Unit closures and the Anthropic dials smoke are the DoD for the 2026 prompt/controls
audit. Without a pin they can vanish via ``@pytest.mark.live``, a path move, or a
narrower ``ci_quality`` selection while the job still goes green. This file pins:

* the modules exist under ``tests/``;
* ``scripts/ci_quality.py`` marker expr still selects them (not live / llm_live / slow);
* Anthropic smoke is ``integration`` (HTTP stub), never ``live`` / ``live_formatter``;
* ``integration-db`` still runs ``tests/integration`` (smoke rides that suite too).
"""

from __future__ import annotations

import ast
import importlib.util

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_QUALITY = REPO_ROOT / "scripts" / "ci_quality.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
# Conflict-linter / cutover pins live in test_conflict_linter_ci_gate.py (A1-scoped).

_CLOSURE_MODULES: tuple[Path, ...] = (
    REPO_ROOT / "tests" / "unit" / "test_prompt_audit_closures.py",
    REPO_ROOT / "tests" / "unit" / "test_llm_controls.py",
    REPO_ROOT / "tests" / "integration" / "test_llm_controls_anthropic_smoke.py",
)

_SMOKE = _CLOSURE_MODULES[-1]
_FORBIDDEN_SMOKE_MARKERS = frozenset({"live", "llm_live", "slow", "live_formatter"})


def _ci_quality_marker_expr() -> str:
    spec = importlib.util.spec_from_file_location("ci_quality_gates_under_test", CI_QUALITY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expr = getattr(module, "_PYTEST_MARKER_EXPR", None)
    assert isinstance(expr, str), "ci_quality must expose _PYTEST_MARKER_EXPR"
    assert expr.strip(), "ci_quality must expose _PYTEST_MARKER_EXPR"
    return expr


def _module_pytestmark_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        value = node.value
        elts: list[ast.expr] = list(value.elts) if isinstance(value, ast.List) else [value]
        for elt in elts:
            mark = _mark_name(elt)
            if mark is not None:
                names.add(mark)
    return names


def _mark_name(node: ast.expr) -> str | None:
    """``pytest.mark.foo`` or ``pytest.mark.foo()`` → ``foo``."""
    call = node
    if isinstance(call, ast.Call):
        call = call.func
    if not isinstance(call, ast.Attribute):
        return None
    if not isinstance(call.value, ast.Attribute):
        return None
    if not (isinstance(call.value.value, ast.Name) and call.value.value.id == "pytest"):
        return None
    if call.value.attr != "mark":
        return None
    return call.attr


def test_prompt_controls_modules_exist() -> None:
    missing = [str(path.relative_to(REPO_ROOT)) for path in _CLOSURE_MODULES if not path.is_file()]
    assert not missing, f"prompt/controls DoD modules missing: {missing}"


def test_ci_quality_marker_expr_keeps_closures_selected() -> None:
    """PR quality must not deselect unit closures or the HTTP-stubbed Anthropic smoke."""
    expr = _ci_quality_marker_expr()
    assert "not live" in expr
    assert "not llm_live" in expr
    assert "not slow" in expr
    # Narrowing to unit-only would drop the Anthropic transport smoke.
    assert "not integration" not in expr.replace(" ", "")


def test_anthropic_smoke_is_integration_not_live() -> None:
    marks = _module_pytestmark_names(_SMOKE)
    assert "integration" in marks, "Anthropic dials smoke must ride tests/integration (HTTP stub)"
    leaked = marks & _FORBIDDEN_SMOKE_MARKERS
    assert not leaked, f"smoke must stay on PR path; remove markers {sorted(leaked)}"


def test_integration_db_job_still_runs_integration_suite() -> None:
    loaded = cast("dict[str, Any]", yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8")))
    job = loaded["jobs"]["integration-db"]
    commands = [str(step["run"]) for step in job["steps"] if isinstance(step, dict) and "run" in step]
    assert any("pytest" in cmd and "tests/integration" in cmd for cmd in commands)


@pytest.mark.parametrize(
    "rel",
    [str(path.relative_to(REPO_ROOT).as_posix()) for path in _CLOSURE_MODULES],
)
def test_closure_module_is_importable(rel: str) -> None:
    path = REPO_ROOT / rel
    spec = importlib.util.spec_from_file_location(f"closure_{path.stem}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
