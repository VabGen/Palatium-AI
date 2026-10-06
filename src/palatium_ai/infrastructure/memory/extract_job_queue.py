# src/palatium_ai/infrastructure/memory/extract_job_queue.py

"""In-memory + Postgres SKIP LOCKED extract job queues (Wave M3)."""

from __future__ import annotations

import asyncio

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update

from palatium_ai.domain.memory.extract_queue import ExtractJobRecord, ExtractQueueStats
from palatium_ai.infrastructure.database.models.memory_extract_job import MemoryExtractJobORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DEFAULT_LEASE_SECONDS = 300
_DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 5


class InMemoryExtractJobQueue:
    """Process-local queue with lease reclaim (unit tests / no Postgres)."""

    def __init__(
        self,
        *,
        max_queue: int = 256,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._max_queue = max(1, max_queue)
        self._lease_seconds = max(1, lease_seconds)
        self._max_attempts = max(1, max_attempts)
        self._rows: dict[UUID, ExtractJobRecord] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> bool:
        async with self._lock:
            for row in self._rows.values():
                if row.thread_id == thread_id and row.task_id == task_id:
                    if row.status == "dead":
                        self._rows[row.id] = row.model_copy(
                            update={
                                "status": "pending",
                                "attempts": 0,
                                "available_at": datetime.now(UTC),
                                "leased_until": None,
                                "last_error": None,
                            }
                        )
                        return True
                    return True
            pending = sum(1 for r in self._rows.values() if r.status in {"pending", "running"})
            if pending >= self._max_queue:
                return False
            job_id = uuid4()
            now = datetime.now(UTC)
            self._rows[job_id] = ExtractJobRecord(
                id=job_id,
                thread_id=thread_id,
                task_id=task_id,
                user_id=user_id,
                org_id=org_id,
                status="pending",
                attempts=0,
                max_attempts=self._max_attempts,
                available_at=now,
                created_at=now,
            )
            return True

    async def claim(self) -> ExtractJobRecord | None:
        async with self._lock:
            now = datetime.now(UTC)
            candidates = [
                row
                for row in self._rows.values()
                if (
                    row.status == "pending"
                    and (row.available_at is None or row.available_at <= now)
                )
                or (
                    row.status == "running"
                    and row.leased_until is not None
                    and row.leased_until < now
                )
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda r: r.created_at or now)
            row = candidates[0]
            claimed = row.model_copy(
                update={
                    "status": "running",
                    "attempts": row.attempts + 1,
                    "leased_until": now + timedelta(seconds=self._lease_seconds),
                    "available_at": now,
                }
            )
            self._rows[row.id] = claimed
            return claimed

    async def complete(self, job_id: UUID) -> None:
        async with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return
            self._rows[job_id] = row.model_copy(
                update={"status": "done", "leased_until": None, "last_error": None}
            )

    async def fail(self, job_id: UUID, *, error: str) -> None:
        async with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return
            now = datetime.now(UTC)
            if row.attempts >= row.max_attempts:
                self._rows[job_id] = row.model_copy(
                    update={"status": "dead", "leased_until": None, "last_error": error[:2000]}
                )
                return
            delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, row.attempts - 1))
            self._rows[job_id] = row.model_copy(
                update={
                    "status": "pending",
                    "leased_until": None,
                    "available_at": now + timedelta(seconds=delay),
                    "last_error": error[:2000],
                }
            )

    async def stats(self) -> ExtractQueueStats:
        async with self._lock:
            now = datetime.now(UTC)
            pending_times: list[datetime] = []
            depth = 0
            dead = 0
            for row in self._rows.values():
                if row.status == "dead":
                    dead += 1
                elif row.status == "pending":
                    depth += 1
                    if row.created_at is not None:
                        pending_times.append(row.created_at)
                elif row.status == "running":
                    depth += 1
            lag = 0.0
            if pending_times:
                lag = max(0.0, (now - min(pending_times)).total_seconds())
            return ExtractQueueStats(depth=depth, lag_seconds=lag, dead=dead)


class PostgresExtractJobQueue:
    """Durable extract queue: ``FOR UPDATE SKIP LOCKED`` claim."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_queue: int = 256,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._session_factory = session_factory
        self._max_queue = max(1, max_queue)
        self._lease_seconds = max(1, lease_seconds)
        self._max_attempts = max(1, max_attempts)

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            depth = await session.scalar(
                select(func.count())
                .select_from(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.status.in_(("pending", "running")))
            )
            existing = await session.scalar(
                select(MemoryExtractJobORM).where(
                    MemoryExtractJobORM.thread_id == thread_id,
                    MemoryExtractJobORM.task_id == task_id,
                )
            )
            if existing is not None:
                if existing.status == "dead":
                    existing.status = "pending"
                    existing.attempts = 0
                    existing.available_at = now
                    existing.leased_until = None
                    existing.last_error = None
                    existing.user_id = user_id
                    existing.org_id = org_id
                    await session.commit()
                return True
            if int(depth or 0) >= self._max_queue:
                return False
            session.add(
                MemoryExtractJobORM(
                    id=uuid4(),
                    thread_id=thread_id,
                    task_id=task_id,
                    user_id=user_id,
                    org_id=org_id,
                    status="pending",
                    attempts=0,
                    max_attempts=self._max_attempts,
                    available_at=now,
                )
            )
            await session.commit()
            return True

    async def claim(self) -> ExtractJobRecord | None:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self._lease_seconds)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE memory.extract_jobs AS j
                    SET status = 'running',
                        attempts = j.attempts + 1,
                        leased_until = :lease_until,
                        available_at = :now,
                        updated_at = :now
                    WHERE j.id = (
                        SELECT id
                        FROM memory.extract_jobs
                        WHERE (
                            status = 'pending' AND available_at <= :now
                        ) OR (
                            status = 'running' AND leased_until IS NOT NULL AND leased_until < :now
                        )
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING
                        id, thread_id, task_id, user_id, org_id, status, attempts,
                        max_attempts, available_at, leased_until, last_error, created_at
                    """
                ),
                {"now": now, "lease_until": lease_until},
            )
            row = result.mappings().first()
            await session.commit()
        if row is None:
            return None
        return ExtractJobRecord(
            id=row["id"],
            thread_id=row["thread_id"],
            task_id=row["task_id"],
            user_id=row["user_id"],
            org_id=row["org_id"],
            status="running",
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or self._max_attempts),
            available_at=row["available_at"],
            leased_until=row["leased_until"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )

    async def complete(self, job_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                update(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.id == job_id)
                .values(status="done", leased_until=None, last_error=None, updated_at=now)
            )
            await session.commit()

    async def fail(self, job_id: UUID, *, error: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await session.get(MemoryExtractJobORM, job_id)
            if row is None:
                return
            if row.attempts >= row.max_attempts:
                row.status = "dead"
                row.leased_until = None
                row.last_error = error[:2000]
                row.updated_at = now
            else:
                delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, row.attempts - 1))
                row.status = "pending"
                row.leased_until = None
                row.available_at = now + timedelta(seconds=delay)
                row.last_error = error[:2000]
                row.updated_at = now
            await session.commit()

    async def stats(self) -> ExtractQueueStats:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            depth = await session.scalar(
                select(func.count())
                .select_from(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.status.in_(("pending", "running")))
            )
            dead = await session.scalar(
                select(func.count())
                .select_from(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.status == "dead")
            )
            oldest = await session.scalar(
                select(func.min(MemoryExtractJobORM.created_at)).where(
                    MemoryExtractJobORM.status == "pending"
                )
            )
        lag = 0.0
        if oldest is not None:
            aware = oldest if oldest.tzinfo is not None else oldest.replace(tzinfo=UTC)
            lag = max(0.0, (now - aware).total_seconds())
        return ExtractQueueStats(depth=int(depth or 0), lag_seconds=lag, dead=int(dead or 0))
