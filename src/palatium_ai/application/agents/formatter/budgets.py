# src/palatium_ai/application/agents/formatter/budgets.py

"""Formatter completion token budgets."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.config import (
    FORMATTER_BRAND_MAX_COMPLETION_TOKENS,
    FORMATTER_MAX_COMPLETION_TOKENS,
    FORMATTER_MIN_COMPLETION_TOKENS,
    FormatterStyleHint,
)
from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.domain.llm.models import LLMCompletion

_LENGTH_FINISH = frozenset({"length", "max_tokens"})
_BRAND_STYLES: frozenset[str] = frozenset({"brand_sections_icons", "restructure_sections_icons"})


def formatter_max_tokens(
    payload_text: str,
    *,
    style_hint: FormatterStyleHint | str | None = None,
    final_text_len: int = 0,
) -> int:
    """Completion budget from full user payload AND expected output size."""
    estimated_payload = count_tokens(payload_text) * 2
    # ~2.5 chars per token for RU; +30% headroom for markdown structure.
    estimated_output = int(max(final_text_len / 2.5 * 1.3, 0)) if final_text_len else 0
    estimated = max(estimated_payload, estimated_output)

    ceiling = FORMATTER_MAX_COMPLETION_TOKENS
    if style_hint in _BRAND_STYLES:
        ceiling = FORMATTER_BRAND_MAX_COMPLETION_TOKENS
    return min(max(estimated, FORMATTER_MIN_COMPLETION_TOKENS), ceiling)


def repair_max_tokens(base: int, *, truncated: bool) -> int:
    """On length truncation, double budget once (still capped)."""
    if not truncated:
        return base
    return min(max(base * 2, FORMATTER_MIN_COMPLETION_TOKENS), FORMATTER_MAX_COMPLETION_TOKENS)


def was_truncated(completion: LLMCompletion) -> bool:
    reason = (completion.finish_reason or "").strip().lower()
    return reason in _LENGTH_FINISH
