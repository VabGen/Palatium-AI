# src/palatium_ai/domain/memory/ports.py

"""Порты памяти (DIP): transcript store + cross-thread memory."""

from __future__ import annotations

from typing import Any, Protocol

from palatium_ai.domain.memory.turns import DialogRole, DialogTurn, DialogTurnWindow


class DialogTurnStore(Protocol):
    """Persist / load dialog transcript (ordered turns)."""

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: DialogRole,
        content: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DialogTurn:
        """Append one turn; returns persisted turn with seq."""

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        """Load last-K turns for a thread (oldest → newest)."""


class MemoryPort(Protocol):
    """Cross-thread long-term memory (user/org namespaces). Sleep-time writes here."""

    async def put(
        self,
        *,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, object],
    ) -> None:
        """Upsert a memory item under namespace/key."""

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Fetch one item or None."""

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Keyword/hybrid search within a namespace (budgeted)."""
