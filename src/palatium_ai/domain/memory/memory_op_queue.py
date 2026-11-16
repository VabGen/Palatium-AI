# src/palatium_ai/domain/memory/memory_op_queue.py

"""Durable out-of-band memory ops: promote_entry | clear_user_graph (W11 / SKIP LOCKED)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.extract_queue import DEFAULT_LEASE_SECONDS

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "MemoryOpEnqueueResult",
    "MemoryOpKind",
    "MemoryOpQueuePort",
    "MemoryOpRecord",
    "MemoryOpStatus",
]

MemoryOpKind = Literal["promote_entry", "clear_user_graph"]
MemoryOpStatus = Literal["pending", "running", "done", "dead"]
MemoryOpEnqueueResult = Literal["queued", "duplicate"]


class MemoryOpRecord(BaseModel, frozen=True):
    """One claimable memory op row."""

    id: UUID
    kind: MemoryOpKind
    user_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(default="", max_length=256)
    namespace_json: str = Field(default="[]", max_length=1024)
    reason: str = Field(default="", max_length=64)
    status: MemoryOpStatus = "pending"
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    available_at: datetime | None = None
    leased_until: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None


class MemoryOpQueuePort(Protocol):
    """Durable queue for verified fast-path promote and clear-graph cascade."""

    async def enqueue(
        self,
        *,
        kind: MemoryOpKind,
        user_id: str,
        entry_key: str = "",
        namespace: tuple[str, ...] = (),
        reason: str = "",
    ) -> MemoryOpEnqueueResult: ...

    async def claim(self) -> MemoryOpRecord | None: ...

    async def complete(self, op_id: UUID) -> None: ...

    async def fail(self, op_id: UUID, *, error: str) -> None: ...
