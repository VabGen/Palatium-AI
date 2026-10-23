# tests/integration/test_memory_promotion_claim.py

"""Promote claims and content-driven promotion markers (060 / M5 audit F5–F6).

Both invariants live in SQL, not in Python control flow:

* ``claim_promotion`` is a single ``UPDATE ... WHERE promoted_at IS NULL AND lease free``,
  so exclusivity between two connections is decided by the database. A fake session would
  only assert the shape of the statement;
* ``put`` clears ``promoted_at`` inside ``ON CONFLICT DO UPDATE`` — whether the marker is
  reset depends on JSONB comparison against the *existing* row, which needs Postgres.

The live stand reproduced both failures: a second promoter wrote a twin active
``:MemoryFact`` with one ``node_id``, and a rewritten entry never reached the graph again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.infrastructure.database.models.memory_entry import MemoryEntryORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration()


def _row(user_id: str, key: str, *, text: str, promoted_at: datetime | None = None) -> MemoryEntryORM:
    return MemoryEntryORM(
        user_id=user_id,
        namespace=f"user/{user_id}",
        entry_key=key,
        memory_type="preference",
        value={"kind": "preference", "text": text, "confidence": 0.9, "importance": 0.9},
        search_text=text,
        importance=0.9,
        contains_pii=False,
        promoted_at=promoted_at,
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
async def test_claim_is_a_compare_and_set(requires_database: str) -> None:
    """Only the first promoter wins; the row disappears from the candidate listing."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"claim-{uuid4().hex[:12]}"
    key = "db-port"

    try:
        await _seed(session_factory, user_id, _row(user_id, key, text="port is 5432"))

        assert await port.claim_promotion(namespace=("user", user_id), key=key) is True
        assert await port.claim_promotion(namespace=("user", user_id), key=key) is False
        listed = await port.list_promotion_candidates(user_id=user_id, min_access_frequency=0, min_importance=0.0)
        assert listed == [], "a row under an active claim is not a candidate for a second promoter"

        assert await port.release_promotion(namespace=("user", user_id), key=key) is True
        assert await port.claim_promotion(namespace=("user", user_id), key=key) is True
    finally:
        await _purge(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio()
async def test_expired_claim_lease_is_reclaimable(requires_database: str) -> None:
    """A promoter that died mid-write must not park the candidate forever."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"claim-{uuid4().hex[:12]}"
    key = "db-port"

    try:
        await _seed(session_factory, user_id, _row(user_id, key, text="port is 5432"))
        assert await port.claim_promotion(namespace=("user", user_id), key=key, lease_seconds=60) is True

        async with session_factory() as session:
            await set_rls_user_scope(session, user_id)
            await session.execute(
                update(MemoryEntryORM)
                .where(MemoryEntryORM.entry_key == key)
                .values(promote_claimed_at=datetime.now(UTC) - timedelta(minutes=5))
            )
            await session.commit()

        assert await port.claim_promotion(namespace=("user", user_id), key=key, lease_seconds=60) is True
    finally:
        await _purge(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio()
async def test_mark_promoted_clears_the_claim(requires_database: str) -> None:
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"claim-{uuid4().hex[:12]}"
    key = "db-port"

    try:
        await _seed(session_factory, user_id, _row(user_id, key, text="port is 5432"))
        assert await port.claim_promotion(namespace=("user", user_id), key=key) is True
        assert await port.mark_promoted(namespace=("user", user_id), key=key) is True

        row = await _reload(session_factory, user_id, key)
        assert row.promoted_at is not None
        assert row.promote_claimed_at is None
    finally:
        await _purge(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio()
async def test_rewritten_text_clears_the_promotion_marker(requires_database: str) -> None:
    """F5: the graph must be able to follow the new value, not freeze on the first one."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"claim-{uuid4().hex[:12]}"
    key = "db-port"
    promoted_at = datetime.now(UTC) - timedelta(days=1)

    try:
        await _seed(session_factory, user_id, _row(user_id, key, text="port is 5432", promoted_at=promoted_at))

        await port.put(
            namespace=("user", user_id),
            key=key,
            value={"kind": "preference", "text": "port is 5433", "confidence": 0.9, "importance": 0.9},
        )

        row = await _reload(session_factory, user_id, key)
        assert row.promoted_at is None, "a rewritten entry stayed 'promoted' and can never reach the graph"
        listed = await port.list_promotion_candidates(user_id=user_id, min_access_frequency=0, min_importance=0.0)
        assert [candidate.entry_key for candidate in listed] == [key]
    finally:
        await _purge(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio()
async def test_identical_text_keeps_the_promotion_marker(requires_database: str) -> None:
    """Provenance churn (confidence, task id) must not re-run promote."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory)
    user_id = f"claim-{uuid4().hex[:12]}"
    key = "db-port"
    promoted_at = datetime.now(UTC) - timedelta(days=1)

    try:
        await _seed(session_factory, user_id, _row(user_id, key, text="port is 5433", promoted_at=promoted_at))

        await port.put(
            namespace=("user", user_id),
            key=key,
            value={
                "kind": "preference",
                "text": "port is 5433",
                "confidence": 0.99,
                "importance": 0.9,
                "task_id": "another-task",
            },
        )

        row = await _reload(session_factory, user_id, key)
        assert row.promoted_at == promoted_at
        assert await port.list_promotion_candidates(user_id=user_id, min_access_frequency=0, min_importance=0.0) == []
    finally:
        await _purge(engine, user_id)
        await engine.dispose()
