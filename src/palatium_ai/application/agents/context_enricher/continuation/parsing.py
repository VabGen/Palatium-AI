# src/palatium_ai/application/agents/context_enricher/continuation/parsing.py

"""Parse and coerce continuation-phase LLM JSON."""

from __future__ import annotations

import math

from typing import cast

from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.memory.contextualizer import ContextualizerOutput, ContinuationKind
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import ContinuityPolicy

_EXCERPT_MAX_CHARS = 1500
_QUERY_MAX_CHARS = 32_000
_CONTINUATIONS: frozenset[ContinuationKind] = cast(
    "frozenset[ContinuationKind]",
    frozenset({"format", "answer", "new_topic", "clarify"}),
)
_PRIOR_BOUND_KINDS: frozenset[ContinuationKind] = cast(
    "frozenset[ContinuationKind]",
    frozenset({"answer", "format"}),
)


def coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def coerce_confidence(value: object, default: float) -> float:
    try:
        confidence = float(value)  # type: ignore[arg-type]  # duck-typed coercion; isinstance сузил бы контракт (017)
    except TypeError, ValueError:
        return default
    if not math.isfinite(confidence):
        return default
    return min(max(confidence, 0.0), 1.0)


def coerce_reasoning(value: object) -> str:
    if value is None:
        return "n/a"
    reasoning = str(value).strip()
    return reasoning[:2000] if reasoning else "n/a"


def parse_contextualizer_output(
    raw: str,
    *,
    dialog_window: DialogTurnWindow | None = None,
) -> ContextualizerOutput:
    payload = loads_llm_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("Contextualizer JSON must be an object")

    kind_raw = str(payload.get("continuation_kind", "new_topic"))
    kind: ContinuationKind
    if kind_raw in _CONTINUATIONS:
        kind = cast("ContinuationKind", kind_raw)
    else:
        prior = ContinuityPolicy.prior_assistant_content(None, dialog_window)
        kind = "answer" if prior is not None else "new_topic"

    rewritten = str(payload.get("rewritten_query", "")).strip()
    if not rewritten:
        raise ValueError("rewritten_query empty")

    refers_to_prior = coerce_bool(payload.get("refers_to_prior", False))
    excerpt_text = _resolve_excerpt(
        payload.get("prior_assistant_excerpt"),
        dialog_window=dialog_window,
        kind=kind,
        refers_to_prior=refers_to_prior,
    )
    slot_filled = coerce_bool(payload.get("slot_filled_by_prior", False))
    # Slot fill is only meaningful for prior-bound answers (false_clarify contract).
    choice_slot_filled = slot_filled and kind == "answer" and refers_to_prior

    return ContextualizerOutput(
        rewritten_query=rewritten[:_QUERY_MAX_CHARS],
        continuation_kind=kind,
        confidence=coerce_confidence(payload.get("confidence"), default=0.5),
        refers_to_prior=refers_to_prior,
        prior_assistant_excerpt=excerpt_text,
        reasoning=coerce_reasoning(payload.get("reasoning")),
        choice_slot_filled=choice_slot_filled,
    )


def _resolve_excerpt(
    excerpt: object,
    *,
    dialog_window: DialogTurnWindow | None,
    kind: ContinuationKind,
    refers_to_prior: bool,
) -> str | None:
    """Prefer LLM excerpt; backfill dialog prior only when the ask is prior-bound.

    Never backfill for ``new_topic`` — an empty LLM excerpt there is intentional
    independence and must not poison Continuity false-new_topic recovery (055).
    """
    if isinstance(excerpt, str) and excerpt.strip():
        return excerpt.strip()[:_EXCERPT_MAX_CHARS]
    if excerpt not in (None, "") and not isinstance(excerpt, str):
        text = str(excerpt).strip()
        if text:
            return text[:_EXCERPT_MAX_CHARS]
    if kind not in _PRIOR_BOUND_KINDS and not refers_to_prior:
        return None
    prior = ContinuityPolicy.prior_assistant_content(None, dialog_window)
    return prior[:_EXCERPT_MAX_CHARS] if prior else None
