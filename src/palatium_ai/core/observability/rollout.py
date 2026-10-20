# src/palatium_ai/core/observability/rollout.py

"""Sticky percentage rollout — one bucketing rule for every canary axis.

Sticky by a stable key (user or thread): the same subject always lands in the same
cohort, so a rolling deploy cannot flip its contract mid-conversation. The bucket is
derived from ``hash8`` (already used by the Formatter canary), never from a random
number and never from ``hash()`` (process-randomized for strings).

Semantics shared by every axis (two-key rollout):
``pct <= 0``  → off (safe default: a lone MODE must not flip everyone)
``pct >= 100`` → on for every caller (explicit full cutover)
``1..99``     → deterministic share of subjects.
"""

from __future__ import annotations

from palatium_ai.core.observability.redaction import hash8

_ANONYMOUS = "anonymous"
_BUCKETS = 100


def sticky_bucket(key: str | None) -> int:
    """Return the subject's bucket in ``[0, 100)`` (pure, stable across processes)."""
    normalized = (key or "").strip() or _ANONYMOUS
    return int(hash8(normalized), 16) % _BUCKETS


def is_in_rollout(key: str | None, pct: int) -> bool:
    """Whether ``key`` participates in ``pct`` percent of the cohort."""
    value = int(pct)
    if value <= 0:
        return False
    if value >= _BUCKETS:
        return True
    return sticky_bucket(key) < value
