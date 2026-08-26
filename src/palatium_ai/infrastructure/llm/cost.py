# src/palatium_ai/infrastructure/llm/cost.py

"""Estimate USD cost for an LLM call via LiteLLM pricing tables.

Unknown / local models (no price card) return 0.0 — never invent rates.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def estimate_completion_cost_usd(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return USD cost for prompt+completion tokens, or 0.0 if unknown."""
    if not model or (prompt_tokens <= 0 and completion_tokens <= 0):
        return 0.0
    try:
        from litellm import cost_per_token
    except ImportError:  # pragma: no cover
        return 0.0

    try:
        prompt_cost, completion_cost = cost_per_token(
            model=model,
            prompt_tokens=max(0, prompt_tokens),
            completion_tokens=max(0, completion_tokens),
        )
    except Exception as exc:
        logger.debug(
            "LLM cost estimate unavailable",
            model=model,
            error=str(exc),
        )
        return 0.0

    total = float(prompt_cost) + float(completion_cost)
    return total if total > 0.0 else 0.0
