# palatium_ai/main.py

"""Точка входа приложения."""

from __future__ import annotations

import asyncio

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import build_uvicorn_log_config
from palatium_ai.infrastructure.memory.checkpointer import ensure_psycopg_compatible_loop
from palatium_ai.presentation.app import create_app

# Must run before any asyncio loop is created (psycopg on Windows).
ensure_psycopg_compatible_loop()

settings = get_settings()
app = create_app(settings)


async def main() -> None:
    """Запуск приложения через uvicorn."""
    import uvicorn

    uvicorn.run(
        "palatium_ai.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=settings.app.environment == "development",
        log_level=settings.logging.level.lower(),
        log_config=build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    asyncio.run(main())
