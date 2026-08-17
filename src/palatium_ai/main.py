# palatium_ai/main.py

"""Основной модуль приложения."""

import asyncio
import os

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import logger, setup_logging
from palatium_ai.infrastructure.database.init_db import ensure_database_and_schema, ensure_redis_connection


async def main() -> None:
    """Запуск приложения с инициализацией БД и Redis."""
    print(f"ENV_FILE: {os.getenv('ENV_FILE', 'не задан')}")
    logger.info("Запуск приложения...")

    settings = get_settings()
    setup_logging(settings)

    await ensure_database_and_schema(settings)
    await ensure_redis_connection(settings)


if __name__ == "__main__":
    asyncio.run(main())
