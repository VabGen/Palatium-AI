# tests/unit/test_memory_scoring.py

"""Unit tests for domain/memory/scoring.py (060)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.domain.memory.scoring import (
    ImportanceInputs,
    compute_importance,
    frequency_score,
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
