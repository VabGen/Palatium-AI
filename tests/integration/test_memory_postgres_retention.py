# tests/integration/test_memory_postgres_retention.py

"""Rewriting a memory row must not extend its life (060.8, ``020``).

``RetentionPolicy.memory_expires_at`` documents one contract: "PII clock = created_at only,
access does not extend PII". The upsert used to contradict it — a re-save recomputed
``expires_at`` from ``now``, so every write of an existing PII row pushed the deadline out by
a full window, and writing the row back without ``contains_pii`` reclassified it as medium
(different class, different window). Retention is delete-by-``expires_at``, so both paths
amount to a PII row that is never reclaimed.

This is SQL semantics (``ON CONFLICT DO UPDATE`` against the existing row), so it can only be
verified against a real Postgres: a fake session would assert the shape of a statement, not
what the database does with it (075).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.infrastructure.database.models.memory_entry import MemoryEntryORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration()

# A row written weeks ago whose deadline is already one day away: any "recompute from now"
# path moves it visibly, so the assertion cannot pass by accident.
_SEEDED_AGE_DAYS = 30
_SEEDED_DEADLINE_DAYS = 1


def _seeded_row(user_id: str, key: str, *, text: str, contains_pii: bool, expires_at: datetime) -> MemoryEntryORM:
    created_at = datetime.now(UTC) - timedelta(days=_SEEDED_AGE_DAYS)
    return MemoryEntryORM(
        user_id=user_id,
        namespace=f"user/{user_id}",
        entry_key=key,
        memory_type="fact",
        value={"kind": "fact", "text": text, "contains_pii": contains_pii, "confidence": 0.9},
        search_text=text,
        importance=0.9,
        contains_pii=contains_pii,
        expires_at=expires_at,
        created_at=created_at,
        updated_at=created_at,
    )


async def _seed(session_factory: async_sessionmaker[AsyncSession], user_id: str, row: MemoryEntryORM) -> None:
    async with session_factory() as session:
        await set_rls_user_scope(session, user_id)
        session.add(row)
        await session.commit()


async def _reload(session_factory: async_sessionmaker[AsyncSession], user_id: str, key: str) -> MemoryEntryORM:
    async with session_factory() as session:
        await set_rls_user_scope(session, user_id)
        result = await session.execute(select(MemoryEntryORM).where(MemoryEntryORM.entry_key == key))
        return result.scalar_one()


async def _purge(engine: AsyncEngine, user_id: str) -> None:
    async with AsyncSession(engine) as session:
        await set_rls_user_scope(session, user_id)
        await session.execute(delete(MemoryEntryORM).where(MemoryEntryORM.user_id == user_id))
        await session.commit()


@pytest.mark.asyncio()
async def test_pii_rewrite_does_not_extend_the_deadline_nor_clear_the_flag(requires_database: str) -> None:
    """PII row re-saved twice — once with the flag, once without — keeps deadline and class."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"retention-{uuid4().hex[:12]}"
    key = "ssn"
    deadline = datetime.now(UTC) + timedelta(days=_SEEDED_DEADLINE_DAYS)

    try:
        await _seed(
            session_factory, user_id, _seeded_row(user_id, key, text="SSN is 123-45-6789", contains_pii=True, expires_at=deadline)
        )

        # Same PII fact, restated: the value is refreshed, the deadline is not.
        await port.put(
            namespace=("user", user_id),
            key=key,
            value={"kind": "fact", "text": "SSN is 123-45-6789 (confirmed)", "contains_pii": True, "confidence": 0.95},
        )
        after_pii_write = await _reload(session_factory, user_id, key)
        assert after_pii_write.contains_pii is True
        assert after_pii_write.expires_at == deadline, "a re-save pushed the PII deadline out"
        assert str(after_pii_write.value.get("text", "")).endswith("(confirmed)"), "the value must still be updated"

        # The bypass attempt: write the same key without the PII flag.
        await port.put(
            namespace=("user", user_id),
            key=key,
            value={"kind": "fact", "text": "SSN is 123-45-6789 (again)", "confidence": 0.95},
        )
        after_plain_write = await _reload(session_factory, user_id, key)
        assert after_plain_write.contains_pii is True, "a plain re-save cleared contains_pii and escaped PII retention"
        assert after_plain_write.expires_at == deadline, "clearing the flag moved the row to a longer medium window"
    finally:
        await _purge(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio()
async def test_non_pii_rewrite_keeps_the_sliding_window(requires_database: str) -> None:
    """The invariant is narrow on purpose: activity still refreshes medium/episode retention."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"retention-{uuid4().hex[:12]}"
    key = "preference"
    deadline = datetime.now(UTC) + timedelta(days=_SEEDED_DEADLINE_DAYS)

    try:
        await _seed(
            session_factory, user_id, _seeded_row(user_id, key, text="Prefers tables", contains_pii=False, expires_at=deadline)
        )
        await port.put(
            namespace=("user", user_id),
            key=key,
            value={"kind": "preference", "text": "Prefers tables for agendas", "confidence": 0.9},
        )
        row = await _reload(session_factory, user_id, key)
        assert row.contains_pii is False
        assert row.expires_at is not None
        assert row.expires_at > deadline, "non-PII rows are supposed to slide with activity (060 medium window)"
    finally:
        await _purge(engine, user_id)
        await engine.dispose()
