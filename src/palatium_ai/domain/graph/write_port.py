# src/palatium_ai/domain/graph/write_port.py

"""Graph write port — bi-temporal long-term facts (060 promote; Wave M5)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class GraphFactUpsert(BaseModel):
    """One durable fact/entity for Neo4j (or in-memory stub)."""

    model_config = {"frozen": True}

    user_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="fact", max_length=32)
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_namespace: tuple[str, ...] = ()
    thread_id: str = Field(default="", max_length=128)
    source_type: str = Field(default="promote", max_length=32)
    contains_pii: bool = False
    valid_at: datetime | None = None


class GraphFactRecord(BaseModel):
    """Active or historical MemoryFact snapshot (read model for supersede / temporal)."""

    model_config = {"frozen": True}

    node_id: str
    user_id: str
    entry_key: str
    text: str
    kind: str = "fact"
    importance: float = 0.0
    confidence: float = 0.0
    version: int = 1
    source_type: str = "promote"
    contains_pii: bool = False
    valid_at: datetime | None = None
    created_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    superseded_by: str | None = None


class GraphWritePort(Protocol):
    """Upsert / expire long-term graph facts; separate from read-only GraphPort."""

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        """Persist fact with supersede semantics; returns node id, or ``""`` if blocked."""
        ...

    async def expire_fact(self, *, user_id: str, entry_key: str) -> bool:
        """Fan-out forget/TTL: set ``expired_at`` on linked MemoryFact rows."""
        ...

    async def bump_hebbian_on_entry(self, *, user_id: str, entry_key: str) -> float:
        """Reinforce Hebbian weight on the active fact; return new weight (0 if none)."""
        ...
