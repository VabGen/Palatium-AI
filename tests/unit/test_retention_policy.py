# tests/unit/test_retention_policy.py

"""Pure retention policy unit tests (plans/global-retention W0/W1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.domain.policies.retention import (
    DEFAULT_RETENTION_WINDOWS,
    RetentionPolicy,
    RetentionWindows,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_effective_days_pii_takes_min() -> None:
    assert RetentionPolicy.effective_days(365, contains_pii=True, pii_days=90) == 90
    assert RetentionPolicy.effective_days(30, contains_pii=True, pii_days=90) == 30
    assert RetentionPolicy.effective_days(365, contains_pii=False, pii_days=90) == 365


def test_session_inactivity_cutoff() -> None:
    windows = RetentionWindows(session_days=30)
    cutoff = RetentionPolicy.session_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(days=30)


def test_checkpoint_inactivity_cutoff_hot_wins() -> None:
    windows = RetentionWindows(checkpoint_days=14, session_ttl_seconds=1800)
    cutoff = RetentionPolicy.checkpoint_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(seconds=1800)


def test_checkpoint_inactivity_cutoff_cold_wins_when_hot_longer() -> None:
    windows = RetentionWindows(checkpoint_days=14, session_ttl_seconds=20 * 24 * 3600)
    cutoff = RetentionPolicy.checkpoint_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(days=14)


def test_memory_class_pii_wins_over_episode() -> None:
    assert RetentionPolicy.memory_class(memory_type="episode", contains_pii=True) == "memory_pii"
    assert RetentionPolicy.memory_class(memory_type="episode", contains_pii=False) == "memory_episode"
    assert RetentionPolicy.memory_class(memory_type="fact", contains_pii=False) == "memory_medium"


def test_memory_ttl_episode_and_pii() -> None:
    windows = RetentionWindows(memory_medium_days=30, memory_episode_days=365, memory_pii_days=90)
    assert RetentionPolicy.memory_ttl_days(memory_type="episode", contains_pii=False, windows=windows) == 365
    assert RetentionPolicy.memory_ttl_days(memory_type="episode", contains_pii=True, windows=windows) == 90
    assert RetentionPolicy.memory_ttl_days(memory_type="fact", contains_pii=False, windows=windows) == 30
    assert RetentionPolicy.memory_ttl_days(memory_type="fact", contains_pii=True, windows=windows) == 30


def test_memory_expires_at_from_created_at() -> None:
    expires = RetentionPolicy.memory_expires_at(
        memory_type="fact",
        contains_pii=False,
        created_at=_NOW,
        windows=DEFAULT_RETENTION_WINDOWS,
    )
    assert expires == _NOW + timedelta(days=30)


def test_is_due_respects_hold_and_null() -> None:
    assert not RetentionPolicy.is_due(expires_at=None, now=_NOW)
    assert RetentionPolicy.is_due(expires_at=_NOW, now=_NOW)
    assert not RetentionPolicy.is_due(expires_at=_NOW, now=_NOW, held=True)
    assert not RetentionPolicy.is_due(expires_at=_NOW + timedelta(seconds=1), now=_NOW)


def test_is_due_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RetentionPolicy.is_due(expires_at=_NOW, now=datetime(2026, 10, 5, 12, 0))


def test_decide_hold_and_pii_anonymize() -> None:
    held = RetentionPolicy.decide("memory_medium", held=True)
    assert held.action == "report_only"
    assert held.held is True
    pii = RetentionPolicy.decide("memory_pii")
    assert pii.action == "anonymize"
    after = RetentionPolicy.decide("memory_pii", anonymized=True)
    assert after.action == "delete"


def test_resolve_conflict_keeps_longest() -> None:
    assert RetentionPolicy.resolve_conflict_days(30, 90, 365) == 365
