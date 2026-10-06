#!/usr/bin/env python
"""Enforce the hexagonal import contract from rule 000 (Wave 3.1).

A stdlib-only ``ast`` checker instead of ``import-linter``: adding a dependency is
currently impossible because ``poetry lock`` cannot resolve the existing
``openai`` / ``litellm`` constraint conflict, and the layer rule is small enough
that a 100-line, testable checker is the lower-risk option (050: no dead config,
055: fix the contract, not a one-off).

Edges (importer → forbidden imported layer):
  core          → domain, application, infrastructure, presentation
  domain        → application, infrastructure, presentation
  application   → infrastructure (except the composition root)
  infrastructure→ application, presentation
  presentation  → infrastructure

``core`` may be imported by everyone (rule 000). ``domain`` may import ``core``.
Run ``python scripts/check_import_layers.py`` (exit 1 on violations).
"""

from __future__ import annotations

import ast
import sys

from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "palatium_ai"
_PACKAGE = "palatium_ai"

_LAYERS: tuple[str, ...] = ("core", "domain", "application", "infrastructure", "presentation")
_ALL_LAYERS = frozenset(_LAYERS)

_FORBIDDEN: dict[str, frozenset[str]] = {
    "core": frozenset({"domain", "application", "infrastructure", "presentation"}),
    "domain": frozenset({"application", "infrastructure", "presentation"}),
    "application": frozenset({"infrastructure"}),
    "infrastructure": frozenset({"application", "presentation"}),
    "presentation": frozenset({"infrastructure"}),
}

# Composition root only: builds concrete infrastructure and injects it into application.
_COMPOSITION_ROOT_FILES: frozenset[str] = frozenset(
    {
        "application/wiring",
        "application/bootstrap",
    }
)


@dataclass(frozen=True, slots=True)
class LayerViolation:
    """One forbidden ``importer → imported layer`` edge."""

    importer: str
    line: int
    imported: str
    message: str

    def render(self) -> str:
        return f"{self.importer}:{self.line}: {self.message} (imports {self.imported})"


def _module_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(_SRC).with_suffix("").parts


def _resolve_import(path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve an ``ImportFrom`` to an absolute dotted module (relative imports included)."""
    parts = _module_parts(path)
    package = list(parts) if path.name == "__init__.py" else list(parts[:-1])

    if node.level == 0:
        return node.module

    # Relative: level 1 = current package, level 2 = parent, ...
    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    if not base:
        return None
    if node.module:
        base = [*base, *node.module.split(".")]
    return ".".join(base)


def _target_layer(module: str | None) -> str | None:
    if not module or (module != _PACKAGE and not module.startswith(f"{_PACKAGE}.")):
        return None
    rest = module[len(_PACKAGE) :].lstrip(".")
    if not rest:
        return None
    layer = rest.split(".", 1)[0]
    return layer if layer in _ALL_LAYERS else None


def _iter_python_files() -> list[Path]:
    return sorted(path for path in _SRC.rglob("*.py") if "__pycache__" not in path.parts)


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Line ranges of ``if TYPE_CHECKING:`` blocks — type-only imports, no runtime edge."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            end = node.end_lineno or node.lineno
            ranges.append((node.lineno, end))
    return ranges


def _in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def collect_violations() -> list[LayerViolation]:
    """Return every import that crosses a forbidden layer boundary."""
    violations: list[LayerViolation] = []
    for path in _iter_python_files():
        parts = _module_parts(path)
        rel = "/".join(parts)
        importer_layer = parts[0]
        if importer_layer not in _ALL_LAYERS:
            continue
        forbidden = _FORBIDDEN[importer_layer]
        is_composition_root = rel in _COMPOSITION_ROOT_FILES or f"{rel}.py" in _COMPOSITION_ROOT_FILES
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - would already fail ruff/compile
            violations.append(
                LayerViolation(rel, exc.lineno or 0, "", f"cannot parse: {exc.msg}"),
            )
            continue
        tc_ranges = _type_checking_ranges(tree)
        for node in ast.walk(tree):
            if _in_ranges(getattr(node, "lineno", -1), tc_ranges):
                continue
            if isinstance(node, ast.ImportFrom):
                targets: list[str | None] = [_resolve_import(path, node)]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                continue
            for target in targets:
                layer = _target_layer(target)
                if layer is None or layer == importer_layer or layer not in forbidden:
                    continue
                if is_composition_root and layer == "infrastructure":
                    continue
                violations.append(
                    LayerViolation(
                        importer=rel,
                        line=node.lineno,
                        imported=f"{target}",
                        message=f"{importer_layer}/ must not import {layer}/",
                    ),
                )
    return violations


def main() -> int:
    violations = collect_violations()
    if not violations:
        print("import layers: OK")
        return 0
    print(f"import layers: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  {violation.render()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
