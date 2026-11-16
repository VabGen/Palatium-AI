# src/palatium_ai/infrastructure/memory/memory_op_queue.py

"""In-memory + Postgres SKIP LOCKED memory op queues (W11)."""

from __future__ import annotations

import asyncio
import json

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import text

from palatium_ai.domain.memory.extract_queue import DEFAULT_LEASE_SECONDS
from palatium_ai.domain.memory.memory_op_queue import (
    MemoryOpEnqueueResult,
    MemoryOpKind,
    MemoryOpRecord,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DEFAULT_LEASE_SECONDS = DEFAULT_LEASE_SECONDS
_DEFAULT_MAX_ATTEMPTS = 3
_EXHAUSTED_LEASE_REASON = "lease expired before completion; attempts exhausted"
_BACKOFF_BASE_SECONDS = 5
_ENQUEUE_LOCK_KEY = 4_121_008_312


def _namespace_json(namespace: tuple[str, ...]) -> str:
    return json.dumps(list(namespace), ensure_ascii=False)


class InMemoryMemoryOpQueue:
    """Process-local queue with lease reclaim (unit tests / no Postgres)."""

    def __init__(
        self,
        *,
        lease_seconds: float = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._lease_seconds = max(0.1, lease_seconds)
        self._max_attempts = max(1, max_attempts)
        self._rows: dict[UUID, MemoryOpRecord] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        *,
        kind: MemoryOpKind,
        user_id: str,
        entry_key: str = "",
        namespace: tuple[str, ...] = (),
        reason: str = "",
    ) -> MemoryOpEnqueueResult:
        uid = user_id.strip()
        if not uid:
            msg = "user_id is required"
            raise ValueError(msg)
        key = entry_key.strip()
        ns_json = _namespace_json(namespace)
        async with self._lock:
            for row in self._rows.values():
                if (
                    row.kind == kind
                    and row.user_id == uid
                    and row.entry_key == key
                    and row.namespace_json == ns_json
                    and row.status in {"pending", "running"}
                ):
                    return "duplicate"
            now = datetime.now(UTC)
            op_id = uuid4()
            self._rows[op_id] = MemoryOpRecord(
                id=op_id,
                kind=kind,
                user_id=uid,
                entry_key=key,
                namespace_json=ns_json,
                reason=reason.strip()[:64],
                status="pending",
                attempts=0,
                max_attempts=self._max_attempts,
                available_at=now,
                created_at=now,
            )
            return "queued"

    async def claim(self) -> MemoryOpRecord | None:
        async with self._lock:
            now = datetime.now(UTC)
            self._bury_exhausted_locked(now)
            candidates = [
                row
                for row in self._rows.values()
                if row.attempts < row.max_attempts
                and (
                    (row.status == "pending" and (row.available_at is None or row.available_at <= now))
                    or (row.status == "running" and row.leased_until is not None and row.leased_until < now)
                )
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda r: r.created_at or now)
            chosen = candidates[0]
            updated = chosen.model_copy(
                update={
                    "status": "running",
                    "attempts": chosen.attempts + 1,
                    "leased_until": now + timedelta(seconds=self._lease_seconds),
                    "available_at": now,
                }
            )
            self._rows[chosen.id] = updated
            return updated

    async def complete(self, op_id: UUID) -> None:
        async with self._lock:
            row = self._rows.get(op_id)
            if row is None:
                return
            self._rows[op_id] = row.model_copy(update={"status": "done", "leased_until": None, "last_error": None})

    async def fail(self, op_id: UUID, *, error: str) -> None:
        async with self._lock:
            row = self._rows.get(op_id)
            if row is None:
                return
            now = datetime.now(UTC)
            if row.attempts >= row.max_attempts:
                self._rows[op_id] = row.model_copy(update={"status": "dead", "leased_until": None, "last_error": error[:2000]})
                return
            delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, row.attempts - 1))
            self._rows[op_id] = row.model_copy(
                update={
                    "status": "pending",
                    "leased_until": None,
                    "last_error": error[:2000],
                    "available_at": now + timedelta(seconds=delay),
                }
            )

    def _bury_exhausted_locked(self, now: datetime) -> None:
        for op_id, row in list(self._rows.items()):
            if (
                row.status == "running"
                and row.leased_until is not None
                and row.leased_until < now
                and row.attempts >= row.max_attempts
            ):
                self._rows[op_id] = row.model_copy(
                    update={
                        "status": "dead",
                        "leased_until": None,
                        "last_error": _EXHAUSTED_LEASE_REASON,
                    }
                )

    def pending_kinds(self) -> list[MemoryOpKind]:
        """Test helper: kinds still pending/running."""
        return [r.kind for r in self._rows.values() if r.status in {"pending", "running"}]


class PostgresMemoryOpQueue:
    """Durable memory ops: ``FOR UPDATE SKIP LOCKED`` claim."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: float = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._session_factory = session_factory
        self._lease_seconds = max(0.1, lease_seconds)
        self._max_attempts = max(1, max_attempts)

    async def enqueue(
        self,
        *,
        kind: MemoryOpKind,
        user_id: str,
        entry_key: str = "",
        namespace: tuple[str, ...] = (),
        reason: str = "",
    ) -> MemoryOpEnqueueResult:
        uid = user_id.strip()
        if not uid:
            msg = "user_id is required"
            raise ValueError(msg)
        key = entry_key.strip()
        ns_json = _namespace_json(namespace)
        reason_value = reason.strip()[:64]
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ENQUEUE_LOCK_KEY})
            existing = await session.execute(
                text(
                    """
                    SELECT id FROM memory.ops
                    WHERE kind = :kind
                      AND user_id = :user_id
                      AND entry_key = :entry_key
                      AND namespace_json = :namespace_json
                      AND status IN ('pending', 'running')
                    LIMIT 1
                    """
                ),
                {
                    "kind": kind,
                    "user_id": uid,
                    "entry_key": key,
                    "namespace_json": ns_json,
                },
            )
            if existing.first() is not None:
                await session.commit()
                return "duplicate"
            await session.execute(
                text(
                    """
                    INSERT INTO memory.ops
                        (id, kind, user_id, entry_key, namespace_json, reason, status,
                         attempts, max_attempts, available_at)
                    VALUES
                        (:id, :kind, :user_id, :entry_key, :namespace_json, :reason, 'pending',
                         0, :max_attempts, :now)
                    """
                ),
                {
                    "id": uuid4(),
                    "kind": kind,
                    "user_id": uid,
                    "entry_key": key,
                    "namespace_json": ns_json,
                    "reason": reason_value,
                    "max_attempts": self._max_attempts,
                    "now": now,
                },
            )
            await session.commit()
            return "queued"

    async def claim(self) -> MemoryOpRecord | None:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self._lease_seconds)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE memory.ops
                    SET status = 'dead',
                        leased_until = NULL,
                        last_error = :reason,
                        updated_at = :now
                    WHERE status = 'running'
                      AND leased_until IS NOT NULL
                      AND leased_until < :now
                      AND attempts >= max_attempts
                    """
                ),
                {"now": now, "reason": _EXHAUSTED_LEASE_REASON},
            )
            result = await session.execute(
                text(
                    """
                    UPDATE memory.ops AS j
                    SET status = 'running',
                        attempts = j.attempts + 1,
                        leased_until = :lease_until,
                        available_at = :now,
                        updated_at = :now
                    WHERE j.id = (
                        SELECT id
                        FROM memory.ops
                        WHERE attempts < max_attempts AND (
                            (status = 'pending' AND available_at <= :now) OR
                            (status = 'running' AND leased_until IS NOT NULL AND leased_until < :now)
                        )
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING
                        id, kind, user_id, entry_key, namespace_json, reason, status, attempts,
                        max_attempts, available_at, leased_until, last_error, created_at
                    """
                ),
                {"now": now, "lease_until": lease_until},
            )
            row = result.mappings().first()
            await session.commit()
        if row is None:
            return None
        return MemoryOpRecord(
            id=row["id"],
            kind=row["kind"],
            user_id=row["user_id"],
            entry_key=row["entry_key"] or "",
            namespace_json=row["namespace_json"] or "[]",
            reason=row["reason"] or "",
            status="running",
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or self._max_attempts),
            available_at=row["available_at"],
            leased_until=row["leased_until"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )

    async def complete(self, op_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE memory.ops
                    SET status = 'done', leased_until = NULL, last_error = NULL, updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": op_id, "now": now},
            )
            await session.commit()

    async def fail(self, op_id: UUID, *, error: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        text("SELECT attempts, max_attempts FROM memory.ops WHERE id = :id"),
                        {"id": op_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                await session.commit()
                return
            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or self._max_attempts)
            if attempts >= max_attempts:
                await session.execute(
                    text(
                        """
                        UPDATE memory.ops
                        SET status = 'dead', leased_until = NULL, last_error = :error, updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {"id": op_id, "error": error[:2000], "now": now},
                )
            else:
                delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1))
                await session.execute(
                    text(
                        """
                        UPDATE memory.ops
                        SET status = 'pending',
                            leased_until = NULL,
                            last_error = :error,
                            available_at = :available_at,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": op_id,
                        "error": error[:2000],
                        "available_at": now + timedelta(seconds=delay),
                        "now": now,
                    },
                )
            await session.commit()
