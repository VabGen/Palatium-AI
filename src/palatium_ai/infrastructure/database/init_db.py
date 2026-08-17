# src/palatium_ai/infrastructure/database/init_db.py

"""Функция для инициализации базы данных и схемы при первом запуске."""

import asyncpg
import redis.asyncio as redis

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from palatium_ai.core.config import settings
from palatium_ai.core.logging import logger


async def ensure_database_and_schema() -> None:
    """
    Проверяет существование базы данных и схемы, создаёт их при необходимости.

    Использует стандартную БД 'postgres' для подключения и создания новой БД.
    """
    # 1. Подключение к стандартной БД postgres для управления
    sys_conn = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database="postgres",
    )

    try:
        db_exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            settings.POSTGRES_DB,
        )
        if not db_exists:
            await sys_conn.execute(f"CREATE DATABASE {settings.POSTGRES_DB}")
            print(f"✅ База данных '{settings.POSTGRES_DB}' создана.")
        else:
            print(f"ℹ️ База данных '{settings.POSTGRES_DB}' уже существует.")

    finally:
        await sys_conn.close()

    # 2. Подключаемся к созданной (или существующей) БД для работы со схемой
    engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO)
    async with engine.connect() as conn:
        schema_exists = await conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
            {"schema": settings.POSTGRES_SCHEMA},
        )
        if not schema_exists.scalar():
            await conn.execute(text(f"CREATE SCHEMA {settings.POSTGRES_SCHEMA}"))
            await conn.commit()
            print(f"✅ Схема '{settings.POSTGRES_SCHEMA}' создана.")
        else:
            print(f"ℹ️ Схема '{settings.POSTGRES_SCHEMA}' уже существует.")

    await engine.dispose()


async def ensure_redis_connection() -> None:
    """Проверяет подключение к Redis."""
    try:
        client = redis.from_url(settings.REDIS_URL)
        await client.ping()
        logger.info("✅ Подключение к Redis успешно.")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Redis: {e}")
        raise
    finally:
        await client.close()
