# src/palatium_ai/core/context/tokens.py

"""Unified token counting for context budget (065) — not len(words)."""

from __future__ import annotations

from palatium_ai.core.observability.metrics import agent_metrics

_CHARS_PER_TOKEN_ESTIMATE = 4


def count_tokens(text: str) -> int:
    """Conservative UTF-8 estimate (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def record_context_tokens_used(*, agent_type: str, tokens: int) -> None:
    """Emit palatium_context_tokens_used (040)."""
    if tokens > 0:
        agent_metrics.record_context_tokens(agent_type, tokens)
