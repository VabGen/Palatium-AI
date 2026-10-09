"""Every module under src/ must parse. Catches Python 2 ``except A, B:``."""

from __future__ import annotations

import ast

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"


def test_src_modules_parse() -> None:
    failures: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path}:{exc.lineno}: {exc.msg}")
    assert failures == []
