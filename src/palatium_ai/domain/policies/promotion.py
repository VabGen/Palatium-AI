# src/palatium_ai/domain/policies/promotion.py

"""When a medium-term memory entry may become a long-term graph fact (060)."""

from __future__ import annotations

from datetime import UTC, datetime

from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.memory.scoring import ImportanceInputs, compute_importance, recency_score

# Durable prefs (name, locale, likes) are promote-eligible on write — no wait for
# reconsolidation bumps. Episodic facts still need ``min_access_frequency``.
_PREFERENCE_PROMOTE_KINDS: frozenset[str] = frozenset({"preference"})


class PromotionPolicy:
    """Pure gate: access_frequency + importance; already-promoted rows never re-enter."""

    @staticmethod
    def required_access_frequency(kind: str, *, thresholds: PromotionThresholds) -> int:
        """Access bar for one candidate kind (preferences skip the reconsolidation wait)."""
        if str(kind).strip().lower() in _PREFERENCE_PROMOTE_KINDS:
            return 0
        return thresholds.min_access_frequency

    @staticmethod
    def should_promote(
        candidate: PromotionCandidate,
        *,
        thresholds: PromotionThresholds,
        now: datetime | None = None,
    ) -> bool:
        if candidate.promoted_at is not None:
            return False
        if not candidate.text.strip():
            return False
        min_access = PromotionPolicy.required_access_frequency(
            candidate.kind,
            thresholds=thresholds,
        )
        if candidate.access_frequency < min_access:
            return False
        importance = PromotionPolicy.effective_importance(candidate, now=now)
        return importance >= thresholds.min_importance

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
