# src/palatium_ai/domain/policies/promotion.py

"""When a medium-term memory entry may become a long-term graph fact (060)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.memory.scoring import ImportanceInputs, compute_importance, recency_score
from palatium_ai.domain.memory.types import MemoryTrust, coerce_memory_trust
from palatium_ai.domain.policies.origin_ceiling import OriginCeilingPolicy

# Durable prefs (name, locale, likes) are promote-eligible on write — no wait for
# reconsolidation bumps. Episodic facts still need ``min_access_frequency``.
_PREFERENCE_PROMOTE_KINDS: frozenset[str] = frozenset({"preference"})

#: Why a candidate is not promoted. ``ok`` = eligible; ``pii_hold`` and
#: ``quarantined`` are terminal states a human must clear (020), the rest are waits.
PromotionBlockReason = Literal[
    "ok",
    "already_promoted",
    "empty_text",
    "access",
    "quarantined",
    "pii_hold",
    "importance",
]


class PromotionPolicy:
    """Pure gate: access_frequency + importance; already-promoted rows never re-enter."""

    @staticmethod
    def required_access_frequency(kind: str, *, thresholds: PromotionThresholds) -> int:
        """Access bar for one candidate kind (preferences skip the reconsolidation wait)."""
        if str(kind).strip().lower() in _PREFERENCE_PROMOTE_KINDS:
            return 0
        return thresholds.min_access_frequency

    @staticmethod
    def block_reason(
        candidate: PromotionCandidate,
        *,
        thresholds: PromotionThresholds,
        now: datetime | None = None,
        origin_ceiling: bool = True,
    ) -> PromotionBlockReason:
        """Typed gate outcome — a bool would force callers to re-derive *why* (F3, 055).

        ``pii_hold`` says "waiting for a human", not "nothing to do": the row is a
        standing decision, so the batch aggregates it once instead of logging per row.
        """
        if candidate.promoted_at is not None:
            return "already_promoted"
        if not candidate.text.strip():
            return "empty_text"
        min_access = PromotionPolicy.required_access_frequency(
            candidate.kind,
            thresholds=thresholds,
        )
        trust: MemoryTrust = coerce_memory_trust(candidate.trust) or "inferred"
        if origin_ceiling:
            if trust == "quarantined":
                return "quarantined"
            if trust == "inferred" and candidate.contains_pii:
                return "pii_hold"
            # Inferred rows need corroboration (reconsolidation bumps) before L4.
            if trust == "inferred" and int(candidate.access_frequency) < int(thresholds.min_access_frequency):
                return "access"
        if candidate.access_frequency < min_access:
            return "access"
        importance = PromotionPolicy.effective_importance(candidate, now=now)
        if importance < thresholds.min_importance:
            return "importance"
        return "ok"

    @staticmethod
    def should_promote(
        candidate: PromotionCandidate,
        *,
        thresholds: PromotionThresholds,
        now: datetime | None = None,
        origin_ceiling: bool = True,
    ) -> bool:
        return (
            PromotionPolicy.block_reason(
                candidate,
                thresholds=thresholds,
                now=now,
                origin_ceiling=origin_ceiling,
            )
            == "ok"
        )

    @staticmethod
    def origin_ceiling_allows(
        candidate: PromotionCandidate,
        *,
        min_access_frequency: int,
    ) -> bool:
        trust: MemoryTrust = coerce_memory_trust(candidate.trust) or "inferred"
        return OriginCeilingPolicy.allow_promote(
            trust,
            access_frequency=candidate.access_frequency,
            min_access_frequency=min_access_frequency,
            contains_pii=candidate.contains_pii,
        )

    @staticmethod
    def effective_importance(
        candidate: PromotionCandidate,
        *,
        now: datetime | None = None,
    ) -> float:
        """Blend stored importance with recency/frequency when timestamps exist."""
        stored = max(0.0, min(1.0, candidate.importance))
        if candidate.last_accessed is None:
            return stored
        reference = now or datetime.now(UTC)
        last = candidate.last_accessed
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        computed = compute_importance(
            ImportanceInputs(
                recency_score=recency_score(last_accessed=last, now=reference),
                relevance_score=max(stored, candidate.confidence),
                access_frequency=candidate.access_frequency,
            )
        )
        # Prefer the stronger of stored column vs live formula (never demote a curated score silently).
        return max(stored, computed)
