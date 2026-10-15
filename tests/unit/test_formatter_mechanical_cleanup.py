"""Mechanical cleanup — pre-processor for Formatter LLM (no presentation)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.agent import formatter_max_tokens
from palatium_ai.application.agents.formatter.cleanup import mechanical_cleanup
from palatium_ai.application.agents.formatter.config import (
    FORMATTER_MAX_COMPLETION_TOKENS,
    FORMATTER_MIN_COMPLETION_TOKENS,
)


def test_mechanical_cleanup_strips_trailing_and_collapses_blanks() -> None:
    raw = "line one  \n\n\n\nline two\t\n"
    assert mechanical_cleanup(raw) == "line one\n\nline two"


def test_mechanical_cleanup_closes_unclosed_fence() -> None:
    raw = "before\n```python\nprint(1)\n"
    cleaned = mechanical_cleanup(raw)
    assert cleaned.endswith("```")
    assert cleaned.count("```") == 2


def test_formatter_max_tokens_floor_and_cap() -> None:
    from palatium_ai.application.agents.formatter.config import FORMATTER_BRAND_MAX_COMPLETION_TOKENS

    assert formatter_max_tokens("hi") == FORMATTER_MIN_COMPLETION_TOKENS
    assert FORMATTER_MIN_COMPLETION_TOKENS == 1_024
    assert formatter_max_tokens("x" * 40_000) == FORMATTER_MAX_COMPLETION_TOKENS
    assert formatter_max_tokens("x" * 40_000, style_hint="brand_sections_icons") == FORMATTER_BRAND_MAX_COMPLETION_TOKENS


def test_formatter_max_tokens_scales_with_payload_not_short_ask() -> None:
    """Live bug: short final_text + large attachment still needs ContentDocument headroom."""
    fat_payload = '{"final_text":"дай анализ","attachment_context":"' + ("A" * 8_000) + '"}'
    tokens = formatter_max_tokens(fat_payload)
    assert tokens >= FORMATTER_MIN_COMPLETION_TOKENS
    assert tokens <= FORMATTER_MAX_COMPLETION_TOKENS


def test_repair_max_tokens_doubles_on_truncation() -> None:
    from palatium_ai.application.agents.formatter.agent import _repair_max_tokens

    assert _repair_max_tokens(1_024, truncated=False) == 1_024
    assert _repair_max_tokens(1_024, truncated=True) == 2_048
    assert _repair_max_tokens(3_000, truncated=True) == FORMATTER_MAX_COMPLETION_TOKENS
