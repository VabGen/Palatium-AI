# tests/eval/test_memory_extract_dedup.py

"""Offline baseline for extract-time duplication (M3 audit E5 → M9 step 1/2).

What this file can prove without an LLM: the metric definitions, the recorded baseline of
a fixed "raw extract" corpus, and the split of responsibility between the two dedup levers —

* ``MEMORY_XMEMORY_DECOUPLE`` (batch, exact normalized text) removes verbatim repeats;
* near-paraphrase is only reachable by the extract prompt's dedup contract (E5), because
  no batch-side lexical rule can see it.

Model behaviour (does the LLM actually obey the contract) is **not** measured here: that
needs a real provider and lives behind ``PALATIUM_LIVE_EVAL=1``. The numbers below are the
baseline that M9 gates compare against, so changing normalization or the Jaccard cut-off
must be a deliberate baseline update, not a silent one.
"""

from __future__ import annotations

import pytest

from palatium_ai.domain.memory.duplicates import duplicate_rate, near_duplicate_rate
from palatium_ai.domain.memory.promotion import PromotionCandidate
from palatium_ai.domain.memory.xmemory import decouple_before_aggregate

# One "raw extract" batch as an extractor without a dedup contract produces it: the same
# durable fact restated three ways, one cross-language restatement, and a *supersede*
# pair that must not be mistaken for duplication.
RAW_EXTRACT: tuple[str, ...] = (
    "User prefers the weekly status update in Confluence over the daily standup call",
    "User prefers the weekly status update in Confluence over the daily standup meeting",
    "user prefers the weekly status update in confluence over the daily standup call",
    "User prefers meeting agendas as tables.",
    "User prefers meeting agendas as tables.",
    "Предпочитает повестки встреч в виде таблиц.",
    "Созвон с Acme перенесён на 14:00.",
    "Созвон с Acme перенесён на 15:00.",
)

# Recorded 2026-10-20 with NEAR_DUPLICATE_JACCARD=0.8 over RAW_EXTRACT (8 entries).
BASELINE_DUPLICATE_RATE = 0.25  # 2 verbatim repeats
BASELINE_NEAR_DUPLICATE_RATE = 0.375  # + 1 one-word restatement
# After batch-side collapse only the paraphrase and the translation remain "unresolved".
DECOUPLED_NEAR_DUPLICATE_RATE = 1 / 6


def _candidates(texts: tuple[str, ...]) -> list[PromotionCandidate]:
    return [
        PromotionCandidate(
            namespace=("user", "eval-dedup-user"),
            entry_key=f"add-{index}",
            text=text,
            importance=0.8,
            access_frequency=3,
            user_id="eval-dedup-user",
            confidence=0.9,
            contains_pii=False,
        )
        for index, text in enumerate(texts)
    ]


def test_eval_duplicate_rate_baseline_is_recorded() -> None:
    """Pin the baseline: a metric-definition change must update this number on purpose."""
    assert duplicate_rate(RAW_EXTRACT) == pytest.approx(BASELINE_DUPLICATE_RATE)
    assert near_duplicate_rate(RAW_EXTRACT) == pytest.approx(BASELINE_NEAR_DUPLICATE_RATE)


def test_eval_batch_decouple_removes_only_verbatim_repeats() -> None:
    """xMemory is exact-text only — the reason E5 needs a prompt change, not a flag."""
    collapsed = decouple_before_aggregate(_candidates(RAW_EXTRACT))
    texts = tuple(candidate.text for candidate in collapsed)

    assert len(texts) == 6
    assert duplicate_rate(texts) == 0.0
    assert near_duplicate_rate(texts) == pytest.approx(DECOUPLED_NEAR_DUPLICATE_RATE)
    # The paraphrase survived: still one repeated fact, now a near-duplicate instead of
    # an exact one. A future flag flip cannot close this gap.
    assert near_duplicate_rate(texts) > 0.0


def test_eval_dedup_contract_would_clear_the_near_duplicate() -> None:
    """The prompt contract (E5) targets exactly the residual the batch lever leaves.

    This is a spec-level assertion over a hand-built "contract obeyed" set: it states the
    expected effect and the M9 5.5 threshold (near-duplicate rate -50%), not model output.
    """
    contract_obeyed = (
        "User prefers the weekly status update in Confluence over the daily standup call",
        "User prefers meeting agendas as tables.",
        "Предпочитает повестки встреч в виде таблиц.",
        "Созвон с Acme перенесён на 15:00.",
    )
    assert near_duplicate_rate(contract_obeyed) == 0.0
    assert near_duplicate_rate(contract_obeyed) <= DECOUPLED_NEAR_DUPLICATE_RATE / 2
