# src/palatium_ai/infrastructure/cache/redis.py

"""Redis cache helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis.asyncio as redis

from redis.exceptions import RedisError

from palatium_ai.core.logging import logger

if TYPE_CHECKING:
    from palatium_ai.core.config import Settings


async def ensure_redis_connection(settings: Settings) -> None:
    """Проверяет подключение к Redis."""
    client = await create_redis_client(settings)
    try:
        await client.ping()
        logger.info("Подключение к Redis успешно.")
    except RedisError as exc:
        logger.error("Ошибка подключения к Redis: %s", exc)
        raise
    finally:
        await client.aclose()


async def create_redis_client(settings: Settings) -> redis.Redis:
    """Создаёт asyncio Redis-клиент по DSN из настроек."""
    return redis.from_url(settings.redis.dsn, protocol=2, decode_responses=False)
