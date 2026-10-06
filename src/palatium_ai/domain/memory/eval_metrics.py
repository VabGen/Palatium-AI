# src/palatium_ai/domain/memory/eval_metrics.py

"""Deterministic memory eval metrics (Wave M7 / 040 Recall@k + G7 lite)."""

from __future__ import annotations


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
