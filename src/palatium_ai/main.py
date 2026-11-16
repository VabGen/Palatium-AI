# palatium_ai/main.py

"""Точка входа приложения."""

from __future__ import annotations

import os
import sys

from pathlib import Path

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import build_uvicorn_log_config
from palatium_ai.core.runtime.uvicorn_launch import (
    loop_setting,
    reload_dirs,
    reload_enabled,
    resolve_loop_factory,
)
from palatium_ai.infrastructure.memory.checkpointer import (
    create_psycopg_event_loop,
    psycopg_loop_factory_spec,
)
from palatium_ai.presentation.app import create_app

settings = get_settings()
app = create_app(settings)

# Watch only application sources. Watching the repo root (uvicorn default) pulls in
# `.tox/`, `.venv/`, and other trees — WatchFiles then storms reload and never finishes
# boot (seen under scripts/dev-up.ps1 on Windows after uv tox envs exist).
_SRC_DIR = Path(__file__).resolve().parents[1]


def _checked_loop_setting() -> str:
    """``loop=`` value for uvicorn, verified before the server takes over.

    On Windows the custom factory is required (psycopg needs ``add_reader``), and the
    reference must be importable *before* uvicorn starts: uvicorn resolves ``loop=``
    itself and exits with a generic ``STARTUP_FAILURE`` when it cannot, which reads as
    "server is broken" instead of "event-loop factory reference is stale".
    """
    spec = psycopg_loop_factory_spec()
    setting = loop_setting(is_windows=sys.platform == "win32", factory_spec=spec)
    if setting != spec:
        return setting
    try:
        resolved = resolve_loop_factory(spec)
    except RuntimeError as exc:
        raise SystemExit(f"uvicorn cannot start: {exc}") from exc
    if resolved is not create_psycopg_event_loop:
        raise SystemExit(f"uvicorn cannot start: loop factory {spec!r} resolved to a different object")
    return setting


def main() -> None:
    """Запуск приложения через uvicorn.

    Sync on purpose: ``uvicorn.run`` owns the event loop. Nesting it under
    ``asyncio.run`` raises ``RuntimeError: asyncio.run() cannot be called from a
    running event loop`` when reload is off (host profile / PALATIUM_UVICORN_RELOAD=0).
    The reload supervisor likewise belongs to uvicorn — replacing it with our own
    ``asyncio.run`` would drop hot reload in development.
    """
    import uvicorn

    # Ensure worker logs under --reload flush promptly on Windows pipes.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    # Reload is opt-out via PALATIUM_UVICORN_RELOAD=0 (scripts/dev-up.ps1 sets that:
    # Start-Process + redirected stdio + Windows multiprocessing spawn is unreliable).
    reload = reload_enabled(
        environment=settings.app.environment,
        override=os.environ.get("PALATIUM_UVICORN_RELOAD"),
    )
    uvicorn.run(
        "palatium_ai.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=reload,
        reload_dirs=reload_dirs(reload=reload, source_root=_SRC_DIR),
        # Override uvicorn's win32 Proactor default — psycopg needs Selector (060).
        loop=_checked_loop_setting(),
        log_level=settings.logging.level.lower(),
        log_config=build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main()
