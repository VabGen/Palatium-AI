# palatium_ai/main.py

"""Точка входа приложения."""

from __future__ import annotations

from pathlib import Path

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import build_uvicorn_log_config
from palatium_ai.presentation.app import create_app

settings = get_settings()
app = create_app(settings)

# Watch only application sources. Watching the repo root (uvicorn default) pulls in
# `.tox/`, `.venv/`, and other trees — WatchFiles then storms reload and never finishes
# boot (seen under scripts/dev-up.ps1 on Windows after uv tox envs exist).
_SRC_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    """Запуск приложения через uvicorn.

    Sync on purpose: ``uvicorn.run`` owns the event loop. Nesting it under
    ``asyncio.run`` raises ``RuntimeError: asyncio.run() cannot be called from a
    running event loop`` when reload is off (host profile / PALATIUM_UVICORN_RELOAD=0).
    """
    import os

    import uvicorn

    # Ensure worker logs under --reload flush promptly on Windows pipes.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    # Reload is opt-out via PALATIUM_UVICORN_RELOAD=0. scripts/dev-up.ps1 sets that:
    # Start-Process + redirected stdio + Windows multiprocessing spawn is unreliable
    # (reloader child dies with WaitNamedPipe FileNotFoundError before bind).
    is_dev = settings.app.environment == "development"
    reload_enabled = is_dev and os.environ.get("PALATIUM_UVICORN_RELOAD", "1") != "0"
    uvicorn.run(
        "palatium_ai.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=reload_enabled,
        reload_dirs=[str(_SRC_DIR)] if reload_enabled else None,
        # Override uvicorn's win32 Proactor default — psycopg needs Selector (060).
        loop="palatium_ai.infrastructure.memory.checkpointer:create_psycopg_event_loop",
        log_level=settings.logging.level.lower(),
        log_config=build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main()
