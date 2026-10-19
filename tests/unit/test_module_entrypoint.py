"""`python -m palatium_ai` is a documented entry point, so it must exist and delegate.

Rule 099 (project map) and ``scripts/dev-up.ps1`` both name the short form, but the package
shipped without a ``__main__`` module: the command died with
``No module named palatium_ai.__main__; 'palatium_ai' is a package and cannot be directly
executed``. A documented entry point that does not run is the same class of bug as a gate
that cannot fail (017).

The pin is structural on purpose. Importing the launcher builds settings and the whole ASGI
app (LLM clients, MCP wiring, checkpointer), which a unit test has no reason to pay for —
what needs guarding is that the alias *exists* and calls the single launcher rather than
growing its own ``uvicorn.run`` (that would drift from the event-loop and reload rules in
``core/runtime/uvicorn_launch.py``).
"""

from __future__ import annotations

import ast

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
_ENTRY_PATH = _SRC_ROOT / "palatium_ai" / "__main__.py"


def _parse_entry_point() -> ast.Module:
    return ast.parse(_ENTRY_PATH.read_text(encoding="utf-8"), filename=str(_ENTRY_PATH))


def test_module_entry_point_exists() -> None:
    """`python -m <pkg>` requires `<pkg>/__main__.py`; without it the command cannot run."""
    assert _ENTRY_PATH.is_file()


def test_entry_point_imports_the_single_launcher() -> None:
    """The alias must import `main` from `palatium_ai.main`, not re-implement startup."""
    imports = [
        node for node in ast.walk(_parse_entry_point()) if isinstance(node, ast.ImportFrom) and node.module == "palatium_ai.main"
    ]

    assert imports, "entry point must import from palatium_ai.main"
    assert any(alias.name == "main" for node in imports for alias in node.names)


def test_entry_point_calls_the_launcher_under_the_main_guard() -> None:
    """A bare import of the module must not start a server; `-m` must."""
    guarded_calls = [
        if_node
        for if_node in ast.walk(_parse_entry_point())
        if isinstance(if_node, ast.If) and isinstance(if_node.test, ast.Compare)
        if _is_main_guard(if_node.test)
        and any(
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "main"
            for statement in if_node.body
        )
    ]

    assert guarded_calls, "`main()` must be called under `if __name__ == '__main__'`"


def _is_main_guard(test: ast.Compare) -> bool:
    left = test.left
    comparators = test.comparators
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and len(comparators) == 1
        and isinstance(comparators[0], ast.Constant)
        and comparators[0].value == "__main__"
    )


def test_entry_point_does_not_run_its_own_server() -> None:
    """A second `uvicorn` call would bypass the event-loop factory and reload policy."""
    tree = _parse_entry_point()
    imports_uvicorn = [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "uvicorn" for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "uvicorn")
    ]
    starts_server = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "uvicorn"
    ]

    assert not imports_uvicorn, "the alias must not import uvicorn itself"
    assert not starts_server, "startup belongs to palatium_ai.main:main()"
