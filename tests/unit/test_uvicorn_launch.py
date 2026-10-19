"""Launch parameters for the API process must be decided by code, not by a boot attempt.

Three regressions this file pins:

* the reloader watches the repository root — WatchFiles storms reload over `.venv`/`.tox`
  and the server never finishes boot on Windows;
* the event-loop factory reference drifts from the factory it names — uvicorn then exits
  with a generic ``STARTUP_FAILURE`` instead of a message that names the spec;
* a custom loop factory is passed where it is not needed — on POSIX ``asyncio`` already
  builds a ``SelectorEventLoop``, so the string indirection would be pure ceremony.

Only the small pure module and uvicorn's own resolver are exercised here: the app itself
is never built, so this runs in the PR path without databases or model clients.
"""

from __future__ import annotations

import asyncio
import sys

from pathlib import Path

import pytest

from palatium_ai.core.runtime.uvicorn_launch import (
    loop_setting,
    reload_dirs,
    reload_enabled,
    resolve_loop_factory,
)
from palatium_ai.infrastructure.memory.checkpointer import (
    create_psycopg_event_loop,
    ensure_psycopg_compatible_loop,
    is_psycopg_compatible_loop,
    psycopg_loop_factory_spec,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"


@pytest.mark.parametrize(
    "environment,override,expected",
    (
        ("development", None, True),
        ("development", "1", True),
        ("development", "0", False),
        ("staging", None, False),
        ("production", "1", False),
    ),
)
def test_reload_is_development_only_and_opt_out(environment: str, override: str | None, expected: bool) -> None:
    """`dev-up.ps1` turns the reloader off although the environment stays development."""
    assert reload_enabled(environment=environment, override=override) is expected


def test_reload_dirs_are_absent_while_the_reloader_is_off() -> None:
    """uvicorn warns about (and ignores) reload settings when the reloader is off."""
    assert reload_dirs(reload=False, source_root=_SRC_DIR) is None


def test_reload_dirs_watch_the_source_tree_only() -> None:
    """Watching the repository root pulls `.venv`/`.tox` in and the reloader never settles."""
    dirs = reload_dirs(reload=True, source_root=_SRC_DIR)

    assert dirs == [str(_SRC_DIR)]
    assert _SRC_DIR != _REPO_ROOT
    assert (_SRC_DIR / "palatium_ai").is_dir(), "watch dir must actually contain the package"


def test_uvicorn_resolves_the_watch_dirs() -> None:
    """The value we pass must survive uvicorn's own normalization (no silent drop).

    uvicorn normalizes watch paths only when it considers the config reloadable, which
    requires the app to be the import string — the same shape ``main()`` uses.
    """
    from uvicorn import Config

    watch = reload_dirs(reload=True, source_root=_SRC_DIR)
    config = Config(app="palatium_ai.main:app", reload=True, reload_dirs=watch)

    assert [Path(entry).resolve() for entry in config.reload_dirs] == [_SRC_DIR]


def test_custom_loop_factory_only_on_windows() -> None:
    """A selector factory is redundant where `asyncio` already returns SelectorEventLoop."""
    spec = psycopg_loop_factory_spec()

    assert loop_setting(is_windows=True, factory_spec=spec) == spec
    assert loop_setting(is_windows=False, factory_spec=spec) == "asyncio"


def test_derived_spec_is_what_uvicorn_imports() -> None:
    """Pin uvicorn's contract: `loop=module:attr` must resolve to the factory itself."""
    from uvicorn.importer import import_from_string

    assert import_from_string(psycopg_loop_factory_spec()) is create_psycopg_event_loop


def test_spec_is_derived_from_the_factory() -> None:
    """Renaming the factory must rename the reference — no hand-written path to drift."""
    assert psycopg_loop_factory_spec() == (f"{create_psycopg_event_loop.__module__}:{create_psycopg_event_loop.__qualname__}")


@pytest.mark.parametrize(
    "spec,fragment",
    (
        ("palatium_ai.infrastructure.memory.checkpointer", "module:attr"),
        ("palatium_ai.absent_module:create_psycopg_event_loop", "cannot be imported"),
        ("palatium_ai.infrastructure.memory.checkpointer:absent_attr", "does not point at a callable"),
        ("palatium_ai.infrastructure.memory:__doc__", "does not point at a callable"),
    ),
)
def test_broken_spec_fails_with_the_spec_in_the_message(spec: str, fragment: str) -> None:
    """The operator must see which reference is broken, not uvicorn's generic failure."""
    with pytest.raises(RuntimeError, match=fragment):
        resolve_loop_factory(spec)


def test_factory_returns_a_selector_loop() -> None:
    """psycopg needs `add_reader`; ProactorEventLoop (win32 default) does not provide it."""
    loop = create_psycopg_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


async def _loop_is_compatible() -> bool:
    return ensure_psycopg_compatible_loop()


def test_running_on_the_factory_loop_is_compatible() -> None:
    """`asyncio.run(..., loop_factory=...)` — the path scripts/ use for the checkpointer."""
    assert asyncio.run(_loop_is_compatible(), loop_factory=create_psycopg_event_loop) is True


def test_only_selector_loops_can_serve_psycopg() -> None:
    """The verdict must be about `add_reader`, not about the class name of the day."""
    loop = create_psycopg_event_loop()
    try:
        assert is_psycopg_compatible_loop(loop) is True
    finally:
        loop.close()

    assert is_psycopg_compatible_loop(object()) is False


def test_incompatible_running_loop_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnostic must not stay silent when the loop cannot serve psycopg.

    The win32 branch is forced: on POSIX every asyncio loop is a SelectorEventLoop, so the
    warning would otherwise be unreachable in CI — a gate that cannot fail is not a gate
    (017).
    """
    from palatium_ai.infrastructure.memory import checkpointer

    monkeypatch.setattr(checkpointer, "_IS_WINDOWS", True)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: object())

    assert ensure_psycopg_compatible_loop() is False


@pytest.mark.skipif(sys.platform != "win32", reason="non-Windows loops are SelectorEventLoop by default")
def test_windows_default_loop_would_not_be_compatible() -> None:
    """Documents the reason the factory exists at all: win32 default is Proactor."""
    loop = asyncio.new_event_loop()
    try:
        assert not isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
