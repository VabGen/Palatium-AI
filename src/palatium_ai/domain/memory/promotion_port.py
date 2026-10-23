# src/palatium_ai/domain/memory/promotion_port.py

"""Port for medium-term access tracking + promotion candidate listing (060)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.memory.promotion import DEFAULT_PROMOTE_CLAIM_SECONDS, PromotionCandidate


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

    async def claim_promotion(
        self,
        *,
        namespace: tuple[str, ...],
        key: str,
        lease_seconds: int = DEFAULT_PROMOTE_CLAIM_SECONDS,
    ) -> bool:
        """Reserve the row for one promoter; False when promoted or already claimed.

        The reservation is a compare-and-set, not a check: two promoters that read the
        same candidate must not both proceed (M5 audit F6). A lease older than
        ``lease_seconds`` is reclaimable, so a crashed promoter does not park the row.
        """
        ...

    async def release_promotion(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Drop the reservation after a non-promoting outcome; True when a claim existed."""
        ...

    async def mark_promoted(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Stamp promoted_at and drop the claim; True when a row was updated."""
        ...
