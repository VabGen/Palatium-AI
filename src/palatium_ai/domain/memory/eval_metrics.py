# src/palatium_ai/domain/memory/eval_metrics.py

"""Deterministic memory eval metrics (Wave M7 / 040 Recall@k + G7 lite)."""

from __future__ import annotations

from collections.abc import Sequence


def recall_at_k(*, retrieved_keys: list[str], relevant_keys: frozenset[str], k: int) -> float:
    """Classic set Recall@k: |relevant ∩ top_k| / |relevant|.

    Empty relevant set → 1.0 (nothing to miss). ``k`` clamped to ≥1.
    """
    if not relevant_keys:
        return 1.0
    top = retrieved_keys[: max(1, int(k))]
    hit = sum(1 for key in relevant_keys if key in top)
    return hit / len(relevant_keys)


def mean_recall_at_k(scores: list[float]) -> float:
    """Macro-average of per-query Recall@k scores."""
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def faithfulness_grounded(*, hint_texts: list[str], corpus_texts: frozenset[str]) -> float:
    """Share of recalled hints that are grounded in the store (no hallucinated memory).

    A hint is grounded when it equals or is a contiguous substring of some
    corpus text (case-insensitive). Empty hints → 1.0 (nothing to invent).
    """
    if not hint_texts:
        return 1.0
    corpus_lower = {text.strip().lower() for text in corpus_texts if text.strip()}
    grounded = 0
    for hint in hint_texts:
        normalized = hint.strip().lower()
        if not normalized:
            continue
        if any(normalized == c or normalized in c or c in normalized for c in corpus_lower):
            grounded += 1
    total = sum(1 for h in hint_texts if h.strip())
    if total == 0:
        return 1.0
    return grounded / total


def context_precision_at_k(
    *,
    retrieved_keys: list[str],
    relevant_keys: frozenset[str],
    k: int,
) -> float:
    """Fraction of top-k retrieved keys that are relevant (RAGAS-style precision@k).

    Empty retrieval → 1.0 when there are no relevants, else 0.0.
    """
    top = retrieved_keys[: max(1, int(k))]
    if not top:
        return 1.0 if not relevant_keys else 0.0
    hits = sum(1 for key in top if key in relevant_keys)
    return hits / len(top)


def supersede_precision(
    *,
    superseded_keys: Sequence[str],
    expected_keys: frozenset[str],
) -> float:
    """Share of acted supersedes that were warranted ("вытеснил лишнее").

    No supersedes at all → 1.0: nothing wrong was done. Precision alone cannot see a
    missed contradiction, so it is always reported next to :func:`supersede_recall`.
    """
    acted = set(superseded_keys)
    if not acted:
        return 1.0
    return len(acted & expected_keys) / len(acted)


def supersede_recall(
    *,
    superseded_keys: Sequence[str],
    expected_keys: frozenset[str],
) -> float:
    """Share of contradictions actually resolved ("не вытеснил").

    Blocked writes (PII, policy) show up here as missed supersedes, not as errors — that
    is the point: the corpus measures the *outcome*, not the intent.
    """
    if not expected_keys:
        return 1.0
    return len(set(superseded_keys) & expected_keys) / len(expected_keys)


def reinforcement_lift(
    *,
    reinforced: Sequence[bool],
    selected: Sequence[bool],
) -> float | None:
    """P(selected | reinforced) - P(selected | not reinforced).

    Returns ``None`` when either cohort is empty: with no control group the lift is
    undefined, and silently returning 0.0 would read as "measured, no effect" (050).
    """
    if len(reinforced) != len(selected):
        msg = "reinforced and selected must describe the same facts"
        raise ValueError(msg)
    reinforced_hits = [hit for flag, hit in zip(reinforced, selected, strict=True) if flag]
    control_hits = [hit for flag, hit in zip(reinforced, selected, strict=True) if not flag]
    if not reinforced_hits or not control_hits:
        return None
    return sum(1 for hit in reinforced_hits if hit) / len(reinforced_hits) - (
        sum(1 for hit in control_hits if hit) / len(control_hits)
    )
