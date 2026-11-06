# src/palatium_ai/application/services/memory_corroboration.py

"""Batch inferred→verified upgrades (ADR 0008 / CMD1.6).

Out-of-band only: callers supply a namespace snapshot (job / test). Does not run
on the user-request hot path (060).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.memory.corroboration import (
    CorroborationEntry,
    propose_trust_upgrades,
)
from palatium_ai.domain.memory.types import (
    MEMORY_TRUST_KEY,
    resolve_memory_origin,
    resolve_memory_trust,
)

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)


class MemoryCorroborationService:
    """Apply ``propose_trust_upgrades`` via MemoryPort.put (trust field only)."""

    def __init__(self, memory_port: MemoryPort) -> None:
        self._memory = memory_port

    async def run_for_user(self, *, user_id: str, limit: int = 256) -> int:
        """Load an owner snapshot and persist upgrades (CronJob / consolidate path)."""
        listing = getattr(self._memory, "list_corroboration_entries", None)
        if listing is None:
            logger.warning("memory_corroboration.list_unsupported", user_id=user_id[:64])
            return 0
        items = await listing(user_id=user_id, limit=limit)
        return await self.run_for_entries(self.entries_from_items(items))

    async def run_for_entries(
        self,
        entries: list[CorroborationEntry] | tuple[CorroborationEntry, ...],
    ) -> int:
        """Persist trust upgrades; returns number of rows updated."""
        upgrades = propose_trust_upgrades(entries)
        updated = 0
        for upgrade in upgrades:
            current = await self._memory.get(namespace=upgrade.namespace, key=upgrade.entry_key)
            if current is None:
                continue
            if resolve_memory_trust(current) == "verified":
                continue
            patched = dict(current)
            patched[MEMORY_TRUST_KEY] = "verified"
            await self._memory.put(namespace=upgrade.namespace, key=upgrade.entry_key, value=patched)
            agent_metrics.record_memory_trust_upgrade(reason=upgrade.reason)
            updated += 1
            logger.info(
                "memory_trust_upgraded",
                entry_key=upgrade.entry_key[:128],
                reason=upgrade.reason,
            )
        return updated

    @staticmethod
    def entries_from_items(
        items: list[tuple[tuple[str, ...], str, dict[str, object]]],
    ) -> list[CorroborationEntry]:
        """Build corroboration rows from ``(namespace, entry_key, value)`` triples."""
        out: list[CorroborationEntry] = []
        for namespace, entry_key, value in items:
            text = str(value.get("text", "")).strip()
            if not text:
                continue
            out.append(
                CorroborationEntry(
                    namespace=namespace,
                    entry_key=entry_key,
                    text=text[:2000],
                    trust=resolve_memory_trust(value),
                    origin=resolve_memory_origin(value),
                    source_task_id=str(value.get("source_task_id", "")).strip()[:128],
                )
            )
        return out


__all__ = ["MemoryCorroborationService"]
