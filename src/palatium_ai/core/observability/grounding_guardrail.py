# src/palatium_ai/core/observability/grounding_guardrail.py

"""Sampled LLM-judge for ungrounded (degraded) responses.

Fire-and-forget: never blocks the pipeline. Failures are logged, not raised.
"""

from __future__ import annotations

import json
import random

from collections.abc import Awaitable, Callable
from typing import Any

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.redaction import hash8, redact

logger = get_logger(__name__)

JUDGE_PROMPT = """\
You are a fact-check judge. The user asked a question. The assistant answered
WITHOUT any external sources (grounding degraded). Determine if the answer:

1. Invents specific facts, numbers, dates, names, or citations not derivable
   from general knowledge.
2. Claims certainty about specifics it cannot know.

Return JSON: {"hallucinated": true|false, "reason": "..."}
"""

JudgeFn = Callable[[str, str, str], Awaitable[dict[str, Any]]]


async def _default_judge(_prompt: str, _query: str, _answer: str) -> dict[str, Any]:
    """No-op judge when no LLM is wired — never invents a verdict."""
    return {"hallucinated": False, "reason": "judge_not_configured"}


async def maybe_judge(
    query: str,
    answer: str,
    sample_rate: float,
    *,
    judge: JudgeFn | None = None,
) -> None:
    """Sample degraded turns; increment hallucination counter on positive verdict."""
    rate = max(0.0, min(1.0, float(sample_rate)))
    if rate <= 0.0 or random.random() >= rate:  # noqa: S311 — sampling, not crypto
        return
    agent_metrics.record_grounding_judge_run()
    fn = judge or _default_judge
    try:
        verdict = await fn(JUDGE_PROMPT, query, answer)
        if bool(verdict.get("hallucinated")):
            agent_metrics.record_grounding_hallucination()
            logger.warning(
                "grounding.hallucination_detected",
                query_hash=hash8(query),
                reason=redact(str(verdict.get("reason") or "")) or "",
            )
    except Exception as exc:  # noqa: BLE001 — fire-and-forget must never raise into pipeline
        agent_metrics.record_grounding_judge_failed()
        logger.error("grounding.judge_failed", error=str(exc))


def parse_judge_json(raw: str) -> dict[str, Any]:
    """Parse judge model JSON; fail soft to hallucinated=false."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"hallucinated": False, "reason": "invalid_json"}
    if not isinstance(payload, dict):
        return {"hallucinated": False, "reason": "invalid_payload"}
    return {
        "hallucinated": bool(payload.get("hallucinated")),
        "reason": str(payload.get("reason") or "")[:500],
    }
