# src/palatium_ai/infrastructure/llm/cost.py

"""Estimate USD cost for an LLM call via LiteLLM pricing tables.

Only concrete provider-qualified ids (``openai/gpt-4o``) exist in LiteLLM's price tables.
A gateway tier alias (``tier-small``) is not: the gateway resolves it to a real model, so the
gateway is the only component that can price that call. Callers talking to a gateway must use
the reported ``LLMCompletion.cost_usd`` and treat this function as the last resort.

Unknown / local models (no price card) return 0.0 — never invent rates.
"""

from __future__ import annotations

import structlog

from palatium_ai.core.logging.redact import redact_text

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
    # Bare gateway aliases (``tier-small``) are registered as ``openai/tier-*``
    # at startup (Phase 3); try the qualified id before giving up.
    lookup_model = model.strip()
    if lookup_model.lower().startswith("tier-"):
        lookup_model = f"openai/{lookup_model}"
    try:
        from litellm import cost_per_token
    except ImportError:  # pragma: no cover
        return 0.0

    try:
        prompt_cost, completion_cost = cost_per_token(
            model=lookup_model,
            prompt_tokens=max(0, prompt_tokens),
            completion_tokens=max(0, completion_tokens),
        )
    except Exception as exc:  # noqa: BLE001  # cost is best-effort; a missing price card never invents a rate (050)
        logger.debug(
            "LLM cost estimate unavailable",
            model=model,
            reason="model_not_in_price_table",
            # Provider errors echo the request back; redact before it reaches the log (020).
            detail=redact_text(str(exc)),
        )
        return 0.0

    total = float(prompt_cost) + float(completion_cost)
    return max(0.0, total)
