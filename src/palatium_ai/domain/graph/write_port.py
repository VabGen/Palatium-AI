# src/palatium_ai/domain/graph/write_port.py

"""Graph write port — long-term fact upsert (060 promote; HITL/EXCEPTION at call site)."""

from __future__ import annotations

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
    source_namespace: tuple[str, ...] = ()
    thread_id: str = Field(default="", max_length=128)


class GraphWritePort(Protocol):
    """Upsert long-term graph facts (MERGE semantics); separate from read-only GraphPort."""

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        """Persist fact; returns stable node/edge id."""
        ...
