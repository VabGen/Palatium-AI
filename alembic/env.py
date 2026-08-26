"""Alembic environment: async SQLAlchemy 2 + Settings-backed DSN."""

from __future__ import annotations

import asyncio
import re

from collections.abc import Iterable, MutableMapping
from logging.config import fileConfig
from typing import TYPE_CHECKING, Literal

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.database import (
    metadata as target_metadata,
    models as orm_models,
)

# Bind models so MetaData is fully populated for autogenerate (not a dead import).
_REGISTERED_ORM_MODELS = (
    orm_models.DialogTurnORM,
    orm_models.MemoryItemORM,
    orm_models.SessionORM,
    orm_models.McpToolCallORM,
)

if TYPE_CHECKING:
    from alembic.operations.ops import MigrationScript
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_SCHEMA_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_NameFilterType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
    "check_constraint",
]
_ParentNames = MutableMapping[
    Literal["schema_name", "table_name", "schema_qualified_table_name"],
    str | None,
]


def _validated_schema() -> str:
    schema = get_settings().db.db_schema
    if not _SCHEMA_NAME_RE.fullmatch(schema):
        msg = f"Unsafe POSTGRES_SCHEMA for DDL: {schema!r}"
        raise ValueError(msg)
    return schema


def include_name(
    name: str | None,
    type_: _NameFilterType,
    parent_names: _ParentNames,
) -> bool:
    """Limit autogenerate reflection to the application schema."""
    app_schema = get_settings().db.db_schema
    if type_ == "schema":
        return name in {None, app_schema}
    return parent_names.get("schema_name") in {None, app_schema}


def process_revision_directives(
    migration_ctx: MigrationContext,
    _revision: str | Iterable[str | None] | Iterable[str],
    _directives: list[MigrationScript],
) -> None:
    """Refuse autogenerate when ORM MetaData has no tables (would emit mass drops)."""
    cmd_opts = migration_ctx.config.cmd_opts if migration_ctx.config is not None else None
    if bool(getattr(cmd_opts, "autogenerate", False)) and (not target_metadata.tables or not _REGISTERED_ORM_MODELS):
        raise RuntimeError(
            "Autogenerate refused: ORM MetaData has no tables. "
            "Import models in alembic/env.py, or use `alembic revision -m`."
        )


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection."""
    settings = get_settings()
    context.configure(
        url=settings.db.async_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        process_revision_directives=process_revision_directives,
        version_table="alembic_version",
        version_table_schema=settings.db.db_schema,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations on a sync connection (via run_sync)."""
    settings = get_settings()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        process_revision_directives=process_revision_directives,
        version_table="alembic_version",
        version_table_schema=settings.db.db_schema,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online migrations through a short-lived async engine (NullPool)."""
    settings = get_settings()
    schema = _validated_schema()
    engine = create_async_engine(settings.db.async_dsn, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await connection.commit()
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
