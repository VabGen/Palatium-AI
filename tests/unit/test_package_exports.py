"""Every platform package declares its public API explicitly (rule 010).

Guards the P2/3.5 convention: each `__init__.py` under `src/palatium_ai` states
`__all__` — a namespace package says `__all__ = []` on purpose, it does not stay
silent. Parsed with `ast` (no imports) so the check is deterministic and cannot
pull in settings, drivers or network clients.
"""

from __future__ import annotations

import ast

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "palatium_ai"


def _declares_all(init_path: Path) -> bool:
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            return True
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return True
    return False


def test_every_package_declares_all() -> None:
    packages = sorted(_PACKAGE_ROOT.rglob("__init__.py"))
    assert packages, f"no packages found under {_PACKAGE_ROOT}"

    missing = [path.relative_to(_PACKAGE_ROOT).as_posix() for path in packages if not _declares_all(path)]
    assert not missing, f"missing `__all__` (rule 010, explicit public API): {missing}"
