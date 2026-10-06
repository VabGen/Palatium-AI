# src/palatium_ai/domain/memory/xmemory.py

"""xMemory decouple-before-aggregate (Wave M8, eval-gated).

Collapses near-duplicate promote candidates so one fact is upserted instead
of N noisy siblings. Opt-in via ``MEMORY_XMEMORY_DECOUPLE``.
"""

from __future__ import annotations

import re

from palatium_ai.domain.memory.promotion import PromotionCandidate

_WS = re.compile(r"\s+")


def normalize_episode_text(text: str) -> str:
    """Fingerprint for near-dup detection (trim + collapse whitespace + lower)."""
    return _WS.sub(" ", text.strip().lower())


def decouple_before_aggregate(
    candidates: list[PromotionCandidate],
) -> list[PromotionCandidate]:
    """Keep the strongest candidate per normalized text fingerprint.

    Strength = (importance, access_frequency, confidence). Order of first
    occurrence is preserved among winners.
    """
    winners: dict[str, PromotionCandidate] = {}
    order: list[str] = []
    for candidate in candidates:
        key = normalize_episode_text(candidate.text)
        if not key:
            continue
        prior = winners.get(key)
        if prior is None:
            winners[key] = candidate
            order.append(key)
            continue
        if _stronger(candidate, prior):
            winners[key] = candidate
    return [winners[key] for key in order]


def _stronger(left: PromotionCandidate, right: PromotionCandidate) -> bool:
    left_key = (left.importance, left.access_frequency, left.confidence)
    right_key = (right.importance, right.access_frequency, right.confidence)
    return left_key > right_key
