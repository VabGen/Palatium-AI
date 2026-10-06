# tests/unit/test_memory_scoring.py

"""Unit tests for domain/memory/scoring.py (060 / Wave M2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.domain.memory.scoring import (
    ImportanceInputs,
    compute_importance,
    frequency_score,
    merge_hybrid_memory_hits,
    rank_by_search_importance,
    recency_score,
)


def test_recency_score_fresh_is_high() -> None:
    now = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    last = now - timedelta(hours=1)
    assert recency_score(last_accessed=last, now=now) > 0.9


def test_recency_score_old_decays() -> None:
    now = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    last = now - timedelta(days=30)
    assert recency_score(last_accessed=last, now=now) < 0.1


def test_recency_score_requires_aware_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        recency_score(
            last_accessed=datetime(2026, 1, 1),
            now=datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_frequency_score_saturates() -> None:
    assert frequency_score(0) == 0.0
    assert frequency_score(5) == 0.5
    assert frequency_score(10) == 1.0
    assert frequency_score(100) == 1.0


def test_compute_importance_weighted_sum() -> None:
    inputs = ImportanceInputs(recency_score=1.0, relevance_score=0.5, access_frequency=5)
    score = compute_importance(inputs)
    assert 0.0 < score < 1.0
    assert score > 0.5


def test_merge_hybrid_rrf_prefers_overlap_over_raw_score() -> None:
    """RRF ranks by position, not raw retrieval scores (same contract as knowledge)."""
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    fts = [
        ("only_fts", 0.99, {"_entry_key": "only_fts", "confidence": 0.9, "_access_frequency": 0}),
        ("both", 0.1, {"_entry_key": "both", "confidence": 0.9, "_access_frequency": 0}),
    ]
    vector = [
        ("only_vec", 0.99, {"_entry_key": "only_vec", "confidence": 0.9, "_access_frequency": 0}),
        ("both", 0.1, {"_entry_key": "both", "confidence": 0.9, "_access_frequency": 0}),
    ]
    merged = merge_hybrid_memory_hits(fts, vector, limit=3, fusion="rrf", rrf_k=60, now=now)
    assert merged[0]["_entry_key"] == "both"


def test_search_time_importance_boosts_frequent_fresh_hits() -> None:
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    hits = [
        {
            "_entry_key": "stale",
            "_score": 1.0,
            "_access_frequency": 0,
            "_last_accessed": (now - timedelta(days=30)).isoformat(),
        },
        {
            "_entry_key": "hot",
            "_score": 0.5,
            "_access_frequency": 10,
            "_last_accessed": (now - timedelta(hours=1)).isoformat(),
        },
    ]
    ranked = rank_by_search_importance(hits, limit=2, now=now)
    assert ranked[0]["_entry_key"] == "hot"
    assert ranked[0]["_score"] > ranked[1]["_score"]
