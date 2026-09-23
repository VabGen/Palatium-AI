# src/palatium_ai/domain/memory/promotion_port.py

"""Port for medium-term access tracking + promotion candidate listing (060)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.memory.promotion import PromotionCandidate


class MemoryPromotionPort(Protocol):
    """Optional capability on MemoryPort backends that support promote."""

    async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> int:
        """Increment access_frequency; return new count (0 if missing)."""
        ...

    async def list_promotion_candidates(
        self,
        *,
        user_id: str,
        min_access_frequency: int,
        min_importance: float,
        limit: int = 32,
    ) -> list[PromotionCandidate]:
        """Rows for one RLS user_id not yet promoted that meet hard floors."""
        ...

    async def mark_promoted(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Stamp promoted_at; returns True when a row was updated."""
        ...
