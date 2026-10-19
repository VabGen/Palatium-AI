# src/palatium_ai/core/runtime/uvicorn_launch.py

"""Uvicorn launch parameters — plain functions, so the dev/prod matrix is testable.

The entry point (``palatium_ai.main``) owns ``uvicorn.run``; everything around it that
has a *decision* in it lives here: reload on/off, watch directories, and which event-loop
factory uvicorn is given. Keeping this out of ``main.py`` means the rules can be pinned by
unit tests instead of by a manual boot on Windows.

Why the loop factory arrives as a string: uvicorn types ``loop`` as
``LoopFactoryType | str`` and resolves anything that is not a known name through
``import_from_string`` — a callable object is rejected before the server starts. That makes
``module:attr`` a uvicorn contract, not a DI style choice; :func:`resolve_loop_factory`
checks the reference with the same mechanics uvicorn uses, so a rename fails here with the
offending spec in the message instead of as a generic ``STARTUP_FAILURE``.
"""

from __future__ import annotations

import importlib

from pathlib import Path

#: Environment value that marks the local development profile (rule 000 / core config).
_DEVELOPMENT = "development"
#: ``PALATIUM_UVICORN_RELOAD`` is opt-out: any value except "0" leaves the reloader on.
_RELOAD_OFF = "0"
_SPEC_SEPARATOR = ":"
#: uvicorn's stdlib loop name; on POSIX it already returns a ``SelectorEventLoop``.
_STDLIB_ASYNCIO = "asyncio"


def reload_enabled(*, environment: str, override: str | None) -> bool:
    """Reload only in development, and only when not explicitly switched off.

    ``PALATIUM_UVICORN_RELOAD=0`` exists because ``scripts/dev-up.ps1`` launches the API
    with redirected stdio on Windows: the reloader child dies with
    ``WaitNamedPipe FileNotFoundError`` before bind, so the supervisor has to stay off
    even though the environment is ``development``.
    """
    return environment == _DEVELOPMENT and override != _RELOAD_OFF


def reload_dirs(*, reload: bool, source_root: Path) -> list[str] | None:
    """Directories the reloader watches, or ``None`` when the reloader is off.

    uvicorn warns about (and ignores) reload settings while the reloader is off, so the
    caller must pass nothing in that case. While it is on, only the application source
    tree is watched: the repository root pulls in ``.venv``/``.tox``/``node_modules`` and
    WatchFiles then storms reload without ever finishing boot (seen on Windows after uv
    tox environments appear).
    """
    return [str(source_root)] if reload else None


def loop_setting(*, is_windows: bool, factory_spec: str) -> str:
    """Value for uvicorn's ``loop=``.

    A custom factory is only needed on Windows, where asyncio defaults to
    ``ProactorEventLoop`` and psycopg async needs ``add_reader`` (``SelectSelector``).
    Elsewhere ``asyncio`` already builds a ``SelectorEventLoop``, so passing a factory
    would add an import-by-string hop with nothing to gain.

    Event-loop *policies* are not used: deprecated in Python 3.14 and removed in 3.16,
    so ``loop_factory`` is the supported hook.
    """
    return factory_spec if is_windows else _STDLIB_ASYNCIO


def resolve_loop_factory(spec: str) -> object:
    """Resolve ``module:attr`` the way uvicorn's ``import_from_string`` does.

    Used as a pre-flight check before ``uvicorn.run``: a broken reference fails here with
    the offending spec, rather than after uvicorn has started its logger and exited with
    ``STARTUP_FAILURE``.
    """
    module_name, separator, attribute = spec.partition(_SPEC_SEPARATOR)
    if not separator or not module_name or not attribute:
        raise RuntimeError(f"loop factory spec must be 'module:attr', got {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"loop factory module {module_name!r} cannot be imported: {exc}") from exc
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise RuntimeError(f"loop factory {spec!r} does not point at a callable (resolved to {type(factory).__name__})")
    return factory
