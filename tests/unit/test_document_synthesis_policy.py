"""Chunked synthesis plan: a long document is read whole, in bounded calls (065)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from palatium_ai.domain.policies.document_synthesis import DocumentSynthesisPolicy, SynthesisChunk


def _body(chars: int) -> str:
    unit = "Пункт договора: срок оплаты 10 банковских дней. "
    return (unit * (chars // len(unit) + 1))[:chars]


def test_short_body_is_one_chunk() -> None:
    body = _body(1_000)

    assert DocumentSynthesisPolicy.needs_chunking(body_chars=len(body), budget_chars=12_000) is False
    chunks = DocumentSynthesisPolicy.plan(body, budget_chars=12_000, max_chunks=8)

    assert chunks == (SynthesisChunk(index=0, start=0, end=len(body)),)


def test_plan_covers_the_whole_body_without_gaps_or_overlap() -> None:
    body = _body(50_000)
    chunks = DocumentSynthesisPolicy.plan(body, budget_chars=12_000, max_chunks=8)

    assert len(chunks) > 1
    assert chunks[0].start == 0
    assert chunks[-1].end == len(body)
    for previous, current in pairwise(chunks):
        assert current.start == previous.end
    assert "".join(body[chunk.start : chunk.end] for chunk in chunks) == body


def test_max_chunks_wins_over_budget_for_cost_ceiling() -> None:
    """A 500k body must not spawn 42 calls: slices widen to respect the ceiling (080)."""
    body = _body(120_000)
    chunks = DocumentSynthesisPolicy.plan(body, budget_chars=12_000, max_chunks=4)

    assert len(chunks) <= 4
    assert all(chunk.chars >= 12_000 for chunk in chunks)


def test_cut_prefers_a_sentence_boundary() -> None:
    sentence = "Условие номер один. "
    body = sentence * 4_000  # ~80k
    chunks = DocumentSynthesisPolicy.plan(body, budget_chars=12_000, max_chunks=8)

    # Every non-final slice ends right after a sentence separator, not mid-word.
    for chunk in chunks[:-1]:
        assert body[chunk.start : chunk.end].rstrip().endswith(".")


def test_empty_body_has_no_chunks() -> None:
    assert DocumentSynthesisPolicy.plan("", budget_chars=12_000, max_chunks=8) == ()


@pytest.mark.parametrize("budget", (1, 0, -5))
def test_tiny_budget_still_terminates(budget: int) -> None:
    body = _body(200)
    chunks = DocumentSynthesisPolicy.plan(body, budget_chars=budget, max_chunks=4)

    assert chunks
    assert chunks[-1].end == len(body)
    assert all(chunk.chars >= 1 for chunk in chunks)
