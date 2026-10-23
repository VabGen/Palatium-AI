# src/palatium_ai/domain/memory/duplicates.py

"""Duplicate-rate metrics for long-term memory (M9 step 1, measured for E5).

These are **lexical** proxies on purpose: no embedding call, no model, so a baseline is
comparable across runs and cheap enough to assert in CI. They answer "how much of what we
store is a repeat", not "do two sentences mean the same thing" — paraphrase and
cross-language equivalence stay with the extract prompt (E5), which is why the metric is
published separately from the prompt.

Both rates are fractions in ``[0, 1]`` of *entries* (a repeated entry is counted once per
occurrence, so ten copies of one fact score ``0.9``); order matters — an entry counts only
if an earlier one already matched.
"""

from __future__ import annotations

import re

from collections.abc import Iterable

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)

# Calibrated on the E5 fixture (`tests/eval/test_memory_extract_dedup.py`): catches a
# restated fact that lost/gained one qualifier, does not catch paraphrase or translation.
# Named constant — it is the definition of the metric, not a per-call knob (050).
NEAR_DUPLICATE_JACCARD = 0.8


def normalize_memory_text(text: str) -> str:
    """Fingerprint for exact-duplicate detection (trim + collapse whitespace + lower)."""
    return _WHITESPACE.sub(" ", text.strip().lower())


def duplicate_rate(texts: Iterable[str]) -> float:
    """Share of entries whose normalized text already occurred earlier."""
    items = [normalize_memory_text(text) for text in texts]
    present = [item for item in items if item]
    if not present:
        return 0.0
    seen: set[str] = set()
    duplicates = 0
    for item in present:
        if item in seen:
            duplicates += 1
        else:
            seen.add(item)
    return duplicates / len(present)


def near_duplicate_rate(
    texts: Iterable[str],
    *,
    threshold: float = NEAR_DUPLICATE_JACCARD,
) -> float:
    """Share of entries lexically near-duplicating an earlier one (token-set Jaccard).

    Quadratic in the number of distinct texts by design: the callers are one promote
    batch (``<= 128`` rows) or an offline eval, never a request path.
    """
    if not 0.0 <= threshold <= 1.0:
        msg = "threshold must be within [0, 1]"
        raise ValueError(msg)
    items = [_token_set(text) for text in texts]
    present = [item for item in items if item]
    if not present:
        return 0.0
    distinct: list[frozenset[str]] = []
    duplicates = 0
    for tokens in present:
        if any(_jaccard(tokens, prior) >= threshold for prior in distinct):
            duplicates += 1
        else:
            distinct.append(tokens)
    return duplicates / len(present)


def _token_set(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(normalize_memory_text(text)))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
