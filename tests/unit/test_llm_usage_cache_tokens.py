# tests/unit/test_llm_usage_cache_tokens.py

"""Provider prompt-cache fields → LLMUsage (CMD2 observability)."""

from __future__ import annotations

from palatium_ai.infrastructure.llm.litellm_adapter import _parse_usage


def test_parse_usage_openai_cached_tokens_detail() -> None:
    usage = _parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 80},
        }
    )
    assert usage.cache_read_tokens == 80
    assert usage.cache_write_tokens == 0


def test_parse_usage_anthropic_style_cache_fields() -> None:
    usage = _parse_usage(
        {
            "prompt_tokens": 200,
            "completion_tokens": 5,
            "cache_read_input_tokens": 120,
            "cache_creation_input_tokens": 40,
        }
    )
    assert usage.cache_read_tokens == 120
    assert usage.cache_write_tokens == 40


def test_parse_usage_missing_cache_stays_zero() -> None:
    usage = _parse_usage({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0
