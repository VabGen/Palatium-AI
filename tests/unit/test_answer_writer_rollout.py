"""Sticky rollout helper — one bucketing rule for canaries."""

from __future__ import annotations

from palatium_ai.core.observability.formatter_rollout import resolve_formatter_mode
from palatium_ai.core.observability.rollout import is_in_rollout, sticky_bucket


def test_zero_and_hundred_are_hard_limits() -> None:
    assert is_in_rollout("thread-1", 0) is False
    assert is_in_rollout("thread-1", 100) is True
    assert is_in_rollout("thread-1", -5) is False
    assert is_in_rollout("thread-1", 150) is True


def test_bucket_is_stable_and_bounded() -> None:
    first = sticky_bucket("thread-abc")
    assert first == sticky_bucket("thread-abc")
    assert 0 <= first < 100


def test_partial_rollout_is_deterministic() -> None:
    assert is_in_rollout("thread-abc", 5) == is_in_rollout("thread-abc", 5)
    assert is_in_rollout("thread-abc", 5) == (sticky_bucket("thread-abc") < 5)


def test_formatter_canary_keeps_two_key_semantics() -> None:
    assert resolve_formatter_mode("legacy", 100, "u1") == "legacy"
    assert resolve_formatter_mode("schema_first", 0, "u1") == "legacy"
    assert resolve_formatter_mode("schema_first", 100, "u1") == "schema_first"
    expected = "schema_first" if sticky_bucket("u1") < 5 else "legacy"
    assert resolve_formatter_mode("schema_first", 5, "u1") == expected
