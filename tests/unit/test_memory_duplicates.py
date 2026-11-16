# tests/unit/test_memory_duplicates.py

"""Duplicate-rate metrics (M9 step 1): lexical definitions and their limits."""

from __future__ import annotations

import pytest

from palatium_ai.domain.memory.duplicates import (
    NEAR_DUPLICATE_JACCARD,
    duplicate_rate,
    near_duplicate_rate,
    normalize_memory_text,
)


def test_normalize_strips_case_and_whitespace_noise() -> None:
    assert normalize_memory_text("  User   prefers\ttables \n") == "user prefers tables"


def test_duplicate_rate_is_zero_without_entries() -> None:
    assert duplicate_rate(()) == 0.0
    assert duplicate_rate(("", "   ")) == 0.0
    assert near_duplicate_rate(()) == 0.0


def test_duplicate_rate_counts_repeats_not_distinct() -> None:
    assert duplicate_rate(("fact a", "fact b", "fact c")) == 0.0
    # Three entries, two of them repeats → 2/3, not 1/3 of distinct texts.
    assert duplicate_rate(("fact a", "FACT A", "fact  a")) == pytest.approx(2 / 3)
    assert duplicate_rate(("only once",)) == 0.0


def test_duplicate_rate_requires_an_earlier_occurrence() -> None:
    """Order is part of the definition: the first occurrence is never a duplicate."""
    assert duplicate_rate(("a b", "a b")) == pytest.approx(0.5)


def test_near_duplicate_rate_catches_one_word_restatement() -> None:
    texts = (
        "User prefers the weekly status update in Confluence over the daily standup call",
        "User prefers the weekly status update in Confluence over the daily standup meeting",
    )
    assert duplicate_rate(texts) == 0.0  # not identical
    assert near_duplicate_rate(texts) == pytest.approx(0.5)


def test_near_duplicate_rate_does_not_collapse_a_contradiction() -> None:
    """Supersede is not duplication: a changed value must stay visible to the metric.

    If the metric counted these as duplicates, a dedup change would look better by
    silently dropping the newer value — exactly the failure mode M9 must catch.
    """
    texts = ("Созвон с Acme перенесён на 14:00.", "Созвон с Acme перенесён на 15:00.")
    assert near_duplicate_rate(texts) == 0.0


def test_near_duplicate_rate_does_not_see_translation() -> None:
    """Documented blind spot: lexical proxy cannot match a translated restatement."""
    texts = ("User prefers meeting agendas as tables.", "Предпочитает повестки встреч в виде таблиц.")
    assert near_duplicate_rate(texts) == 0.0


def test_near_duplicate_rate_rejects_an_out_of_range_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        near_duplicate_rate(("a", "b"), threshold=1.5)


def test_near_duplicate_threshold_is_the_documented_constant() -> None:
    assert pytest.approx(0.8) == NEAR_DUPLICATE_JACCARD
