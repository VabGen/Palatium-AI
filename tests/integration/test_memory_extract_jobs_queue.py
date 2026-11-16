# tests/integration/test_memory_extract_jobs_queue.py

"""Postgres durable extract queue: SKIP LOCKED claim, lease reclaim, DLQ (M3 audit E4).

Runs only when ``DATABASE_URL`` is set (see ``tests/integration/conftest.py``).
The queue is global by design, so this test reads/claims unrelated rows too: point
``DATABASE_URL`` at a disposable database (075), never at staging/prod.

Rows created here use a unique thread prefix and are deleted in ``finally``.
"""

from __future__ import annotations

import asyncio

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.infrastructure.memory.extract_job_queue import PostgresExtractJobQueue

_LEASE_SECONDS = 1


async def _drain_until(
    queue: PostgresExtractJobQueue,
    *,
    task_id: str,
    attempts: int = 32,
) -> str | None:
    """Claim until our job is seen; returns its id (None if it never surfaced)."""
    for _ in range(attempts):
        record = await queue.claim()
        if record is None:
            return None
        if record.task_id == task_id:
            return str(record.id)
    return None


async def _force_expired_lease(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_id: str,
    attempts: int,
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                """
                UPDATE memory.extract_jobs
                SET attempts = :attempts, leased_until = :expired
                WHERE id = :job_id
                """
            ),
            {
                "attempts": attempts,
                "expired": datetime.now(UTC) - timedelta(seconds=5),
                "job_id": job_id,
            },
        )
        await session.commit()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_skip_locked_claim_is_not_duplicated_between_workers(requires_database: str) -> None:
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, lease_seconds=_LEASE_SECONDS)
    task_id = f"it-{uuid4().hex}"
    try:
        assert await queue.enqueue(thread_id=f"it-{uuid4().hex}", task_id=task_id) == "queued"
        first, second = await asyncio.gather(queue.claim(), queue.claim())
        claimed_ids = [str(r.id) for r in (first, second) if r is not None]
        assert len(claimed_ids) == len(set(claimed_ids))
        assert [r.task_id for r in (first, second) if r is not None].count(task_id) <= 1
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_enqueue_is_idempotent_under_concurrency(requires_database: str) -> None:
    """E6: two concurrent enqueues of one turn must neither raise nor create two rows."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory)
    thread_id = f"it-{uuid4().hex}"
    task_id = f"it-{uuid4().hex}"
    try:
        results = await asyncio.gather(
            queue.enqueue(thread_id=thread_id, task_id=task_id),
            queue.enqueue(thread_id=thread_id, task_id=task_id),
        )
        assert results == ["queued", "queued"]
        async with session_factory() as session:
            rows = await session.scalar(
                text("SELECT count(*) FROM memory.extract_jobs WHERE thread_id = :t AND task_id = :task"),
                {"t": thread_id, "task": task_id},
            )
        assert rows == 1
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_enqueue_revives_dead_job(requires_database: str) -> None:
    """Replay of a dead letter must reset attempts and go back to pending (idempotent enqueue)."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, lease_seconds=_LEASE_SECONDS, max_attempts=1)
    thread_id = f"it-{uuid4().hex}"
    task_id = f"it-{uuid4().hex}"
    try:
        assert await queue.enqueue(thread_id=thread_id, task_id=task_id) == "queued"
        job_id = await _drain_until(queue, task_id=task_id)
        assert job_id is not None
        await _force_expired_lease(session_factory, job_id=job_id, attempts=1)
        for _ in range(4):
            record = await queue.claim()
            assert record is None or record.task_id != task_id

        assert await queue.enqueue(thread_id=thread_id, task_id=task_id) == "queued"
        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT status, attempts FROM memory.extract_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                )
            ).first()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == 0
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_enqueue_refuses_new_job_when_queue_full(requires_database: str) -> None:
    """Capacity is a soft backpressure gate; a duplicate of a queued job is still accepted."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    task_id = f"it-{uuid4().hex}"
    duplicate_task = f"it-{uuid4().hex}"
    thread_id = f"it-{uuid4().hex}"
    try:
        async with session_factory() as session:
            depth = await session.scalar(text("SELECT count(*) FROM memory.extract_jobs WHERE status IN ('pending', 'running')"))
        # Per-owner cap pinned to the global one: this test is about the global ceiling.
        queue = PostgresExtractJobQueue(session_factory, max_queue=int(depth or 0) + 1, max_queue_per_tenant=int(depth or 0) + 1)
        assert await queue.enqueue(thread_id=thread_id, task_id=task_id) == "queued"
        assert await queue.enqueue(thread_id=thread_id, task_id=duplicate_task) == "queue_full"
        # Already queued: idempotent accept, not a capacity rejection.
        assert await queue.enqueue(thread_id=thread_id, task_id=task_id) == "queued"
    finally:
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM memory.extract_jobs WHERE task_id IN (:a, :b)"),
                {"a": task_id, "b": duplicate_task},
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_expired_lease_with_exhausted_attempts_goes_dead(requires_database: str) -> None:
    """Regression for M3 audit E1 on the real SQL path, not the in-memory double."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, lease_seconds=_LEASE_SECONDS, max_attempts=2)
    task_id = f"it-{uuid4().hex}"
    job_id: str | None = None
    try:
        assert await queue.enqueue(thread_id=f"it-{uuid4().hex}", task_id=task_id) == "queued"
        job_id = await _drain_until(queue, task_id=task_id)
        assert job_id is not None

        await _force_expired_lease(session_factory, job_id=job_id, attempts=2)
        for _ in range(4):
            record = await queue.claim()
            assert record is None or record.task_id != task_id

        async with session_factory() as session:
            status = await session.scalar(
                text("SELECT status FROM memory.extract_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )
        assert status == "dead"
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_renew_extends_live_lease_and_refuses_expired_one(requires_database: str) -> None:
    """E2: heartbeat renews on the SQL path; an expired lease is reported as lost."""
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, lease_seconds=_LEASE_SECONDS, max_attempts=3)
    task_id = f"it-{uuid4().hex}"
    try:
        assert await queue.enqueue(thread_id=f"it-{uuid4().hex}", task_id=task_id) == "queued"
        job_id = await _drain_until(queue, task_id=task_id)
        assert job_id is not None

        assert await queue.renew(UUID(job_id)) is True
        async with session_factory() as session:
            await session.execute(
                text("UPDATE memory.extract_jobs SET leased_until = now() + interval '0.1 second' WHERE id = :job_id"),
                {"job_id": job_id},
            )
            await session.commit()

        assert await queue.renew(UUID(job_id)) is True
        async with session_factory() as session:
            remaining = await session.scalar(
                text("SELECT EXTRACT(EPOCH FROM (leased_until - now())) FROM memory.extract_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )
        # A live lease is pushed back to a full lease window, not left at 0.1 s.
        assert remaining is not None
        assert float(remaining) > _LEASE_SECONDS * 0.5

        await _force_expired_lease(session_factory, job_id=job_id, attempts=1)
        assert await queue.renew(UUID(job_id)) is False
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_expired_lease_below_max_attempts_is_reclaimed(requires_database: str) -> None:
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, lease_seconds=_LEASE_SECONDS, max_attempts=3)
    task_id = f"it-{uuid4().hex}"
    try:
        assert await queue.enqueue(thread_id=f"it-{uuid4().hex}", task_id=task_id) == "queued"
        job_id = await _drain_until(queue, task_id=task_id)
        assert job_id is not None

        await _force_expired_lease(session_factory, job_id=job_id, attempts=1)
        reclaimed = None
        for _ in range(32):
            record = await queue.claim()
            if record is not None and record.task_id == task_id:
                reclaimed = record
                break
            if record is None:
                break
        assert reclaimed is not None
        assert reclaimed.attempts == 2
    finally:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memory.extract_jobs WHERE task_id = :t"), {"t": task_id})
            await session.commit()
        await engine.dispose()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_per_owner_cap_does_not_lock_out_other_owners(requires_database: str) -> None:
    """E7: one owner saturating its share must not refuse everyone else's extract.

    Real SQL, not the in-memory double: the check lives inside the insert's ``WHERE``, so a
    concurrent enqueue cannot slip past it (the same reason E6 needs the advisory lock).
    """
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    queue = PostgresExtractJobQueue(session_factory, max_queue=8, max_queue_per_tenant=2)
    noisy = f"it-noisy-{uuid4().hex}"
    quiet = f"it-quiet-{uuid4().hex}"
    try:
        assert await queue.enqueue(thread_id="it-noisy", task_id="n1", user_id=noisy) == "queued"
        assert await queue.enqueue(thread_id="it-noisy", task_id="n2", user_id=noisy) == "queued"
        assert await queue.enqueue(thread_id="it-noisy", task_id="n3", user_id=noisy) == "tenant_full"

        # The refusal is per owner: the shared backlog still has room, a second owner is admitted.
        assert await queue.enqueue(thread_id="it-quiet", task_id="q1", user_id=quiet) == "queued"
        # Idempotency beats capacity: re-enqueueing an existing task is not a new job.
        assert await queue.enqueue(thread_id="it-noisy", task_id="n1", user_id=noisy) == "queued"
    finally:
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM memory.extract_jobs WHERE user_id IN (:a, :b)"),
                {"a": noisy, "b": quiet},
            )
            await session.commit()
        await engine.dispose()
