"""Unit tests for dynamic LLM timeout formula (Phase 4)."""

from __future__ import annotations

from palatium_ai.domain.policies.llm_timeout import compute_llm_timeout_seconds


def test_timeout_floor() -> None:
    assert compute_llm_timeout_seconds(prompt_tokens=0, max_tokens=0) == 5.0


def test_timeout_cap() -> None:
    assert compute_llm_timeout_seconds(prompt_tokens=100000, max_tokens=100000) == 90.0


def test_timeout_formula() -> None:
    # 3 + 1000*0.01 + 2000*0.05 = 3 + 10 + 100 = 113 → cap 90
    result = compute_llm_timeout_seconds(prompt_tokens=1000, max_tokens=2000)
    assert result == 90.0


def test_timeout_mid_range() -> None:
    # 3 + 100*0.01 + 100*0.05 = 3 + 1 + 5 = 9
    assert compute_llm_timeout_seconds(prompt_tokens=100, max_tokens=100) == 9.0
