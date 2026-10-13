# src/palatium_ai/application/agents/formatter/budgets.py

"""Formatter completion token budgets."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.config import (
    FORMATTER_MAX_COMPLETION_TOKENS,
    FORMATTER_MIN_COMPLETION_TOKENS,
)
from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.domain.llm.models import LLMCompletion

_LENGTH_FINISH = frozenset({"length", "max_tokens"})


def formatter_max_tokens(payload_text: str) -> int:
    """Completion budget from full user payload (not final_text alone)."""
    estimated = count_tokens(payload_text) * 2
    return min(max(estimated, FORMATTER_MIN_COMPLETION_TOKENS), FORMATTER_MAX_COMPLETION_TOKENS)


def repair_max_tokens(base: int, *, truncated: bool) -> int:
    """On length truncation, double budget once (still capped)."""
    if not truncated:
        return base
    return min(max(base * 2, FORMATTER_MIN_COMPLETION_TOKENS), FORMATTER_MAX_COMPLETION_TOKENS)


def was_truncated(completion: LLMCompletion) -> bool:
    reason = (completion.finish_reason or "").strip().lower()
    return reason in _LENGTH_FINISH
