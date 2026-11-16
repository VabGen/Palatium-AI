# src/palatium_ai/domain/policies/origin_ceiling.py

"""ASI-06 origin ceiling: demote/exclude/promote gates (ADR 0008, 055).

Pure policy — no I/O. Callers pass resolved ``MemoryTrust`` from
``domain.memory.types.resolve_memory_trust``.
"""

from __future__ import annotations

from palatium_ai.domain.memory.types import MemoryTrust

#: Score multiplier for ``inferred`` hits on hot-path Select (verified = 1.0).
INFERRED_SCORE_FACTOR = 0.5


class OriginCeilingPolicy:
    """Gate recall ranking and L4 promote eligibility by staged trust."""

    @staticmethod
    def allow_in_recall(trust: MemoryTrust) -> bool:
        """``quarantined`` never enters the prompt."""
        return trust != "quarantined"

    @staticmethod
    def adjust_score(score: float, trust: MemoryTrust) -> float:
        """Demote inferred relative to verified; quarantined callers should skip first."""
        if trust == "inferred":
            return max(0.0, float(score) * INFERRED_SCORE_FACTOR)
        return max(0.0, float(score))

    @staticmethod
    def allow_promote(
        trust: MemoryTrust,
        *,
        access_frequency: int,
        min_access_frequency: int,
        contains_pii: bool,
    ) -> bool:
        """Verified follows existing thresholds elsewhere; inferred needs corroboration signal.

        ``access_frequency >= min_access_frequency`` stands in for batch corroboration /
        reconsolidation when trust is still ``inferred``. PII inferred never auto-promotes.
        """
        if trust == "quarantined":
            return False
        if trust == "verified":
            return True
        if contains_pii:
            return False
        return int(access_frequency) >= int(min_access_frequency)


__all__ = ["INFERRED_SCORE_FACTOR", "OriginCeilingPolicy"]
