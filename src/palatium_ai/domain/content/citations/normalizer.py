# src/palatium_ai/domain/content/citations/normalizer.py

"""Resolve provider citations against the answer they annotate (W3a, pure).

Two questions are asked of every citation, and they are different:

1. Does ``answer_range`` actually fit the answer text? An offset past the end means
   the provider and we disagree about the text — the citation points nowhere, so it
   is dropped rather than clamped to the last character.
2. Does ``quote`` occur in the answer? A quote the model never wrote is an attribution
   the answer does not support; it is reported as ``unanchored`` and dropped.

Whitespace is collapsed **only for the comparison** — the stored ``quote`` is never
mutated (a citation whose text differs from the source is exactly what a reviewer
needs to see).
"""

from __future__ import annotations

import re

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from palatium_ai.domain.content.citations.models import CitationAnchor, CitationRef

#: Closed set (010): the denominator of the resolution rate is every emitted citation.
CitationOutcome = Literal["resolved", "out_of_range", "unanchored"]

_WHITESPACE_RUN = re.compile(r"\s+")
#: A provider can attach hundreds of annotations to one answer; the UI shows a handful.
_MAX_CITATIONS = 32


class NormalizedCitations(BaseModel):
    """Citations that survived resolution, plus the verdict for every input citation."""

    model_config = {"frozen": True}

    resolved: tuple[CitationRef, ...] = ()
    #: One ``(anchor, outcome)`` per INPUT citation, in order — duplicates included,
    #: because the resolution rate must be counted against what the provider emitted,
    #: not against what we chose to keep (dropping hard cases must not raise the rate).
    outcomes: tuple[tuple[CitationAnchor, CitationOutcome], ...] = ()

    @property
    def emitted(self) -> int:
        return len(self.outcomes)

    @property
    def out_of_range(self) -> int:
        return sum(1 for _, outcome in self.outcomes if outcome == "out_of_range")

    @property
    def unanchored(self) -> int:
        return sum(1 for _, outcome in self.outcomes if outcome == "unanchored")


def normalize_for_match(text: str) -> str:
    """Whitespace-collapsed text for quote comparison only (never for display)."""
    return _WHITESPACE_RUN.sub(" ", text or "").strip()


def classify(citation: CitationRef, answer_text: str) -> CitationOutcome:
    """Where this citation stands relative to ``answer_text``."""
    span = citation.answer_range
    if span is not None and span[1] > len(answer_text):
        return "out_of_range"
    quote = citation.quote
    normalized_quote = normalize_for_match(quote) if quote is not None else ""
    if normalized_quote and normalized_quote not in normalize_for_match(answer_text):
        return "unanchored"
    return "resolved"


def normalize_citations(citations: Iterable[CitationRef], *, answer_text: str) -> NormalizedCitations:
    """Drop out-of-range and unanchored citations, dedupe, cap, keep document order.

    ``answer_text`` is the exact text the provider annotated — for OpenAI-style
    annotations that is the assistant message, so callers must pass the raw provider
    output, not a reformatted document (an offset is only meaningful in its own
    coordinate space).
    """
    kept: list[CitationRef] = []
    seen: set[tuple[str, str, tuple[int, int] | None]] = set()
    outcomes: list[tuple[CitationAnchor, CitationOutcome]] = []
    for citation in citations:
        outcome = classify(citation, answer_text)
        outcomes.append((citation.anchor, outcome))
        if outcome != "resolved":
            continue
        key = (citation.anchor, citation.source_ref, citation.answer_range)
        if key in seen:
            continue
        seen.add(key)
        kept.append(citation)
        if len(kept) >= _MAX_CITATIONS:
            break
    return NormalizedCitations(resolved=tuple(kept), outcomes=tuple(outcomes))


__all__ = ["CitationOutcome", "NormalizedCitations", "classify", "normalize_citations", "normalize_for_match"]
