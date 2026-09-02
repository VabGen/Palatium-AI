# src/palatium_ai/infrastructure/database/init_db.py

"""Функция для инициализации базы данных и схемы при первом запуске."""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from palatium_ai.core.logging import logger

if TYPE_CHECKING:
    from palatium_ai.core.config import Settings


async def ensure_database_and_schema(settings: Settings) -> None:
    """
    Проверяет существование базы данных и схемы, создаёт их при необходимости.

    Использует стандартную БД 'postgres' для подключения и создания новой БД.
    """
    db_cfg = settings.db

    sys_conn = await asyncpg.connect(
        host=db_cfg.host,
        port=db_cfg.port,
        user=db_cfg.user,
        password=db_cfg.password.get_secret_value(),
        database="postgres",
    )

    try:
        db_exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            db_cfg.db,
        )

        if not db_exists:
            await sys_conn.execute(f'CREATE DATABASE "{db_cfg.db}"')
            logger.info("База данных '%s' создана.", db_cfg.db)
        else:
            logger.info("База данных '%s' уже существует.", db_cfg.db)

    finally:
        await sys_conn.close()

    should_echo_sql = db_cfg.echo and settings.logging.level.upper() == "DEBUG"
    engine = create_async_engine(db_cfg.async_dsn, echo=should_echo_sql)
    try:
        async with engine.connect() as conn:
            schema_exists = await conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
                {"schema": db_cfg.db_schema},
            )

            if not schema_exists.scalar():
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{db_cfg.db_schema}"'))
                await conn.commit()
                logger.info("Схема '%s' создана.", db_cfg.db_schema)
            else:
                logger.info("Схема '%s' уже существует.", db_cfg.db_schema)
    finally:
        await engine.dispose()
