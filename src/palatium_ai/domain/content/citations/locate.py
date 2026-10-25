# src/palatium_ai/domain/content/citations/locate.py

"""Locate a citation inside the source text we actually sent (W3b-2, pure).

The coordinate space is the one thing this module must get right. There is exactly
one text shared by the provider and by us: ``AttachmentContent.safe_text`` — the
fenced body that left our side. Several other spans look like offsets and are not:

* ``content_block_location`` indexes the provider's own content blocks, not characters.
  The adapter still stores them in ``source_range`` for honesty, but they cannot
  highlight anything;
* ``answer_range`` indexes the raw answer the provider wrote; after ``schema_first``
  the document is rebuilt from blocks, so it addresses nothing rendered;
* page numbers carry no character span at all.

So the offset is a **hint** and the ``quote`` is the evidence: the provider quotes text
it was given, so a verbatim (whitespace-normalised) match is deterministic and survives
our own prefix (the fence) and budget trimming (head+tail) that shift every offset.
When the evidence does not settle on exactly one place, the answer is "we do not know"
— never "the nearest-looking span" (055).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from palatium_ai.core.types.citations import CITATION_WINDOW_CHARS, CITATION_WINDOW_PAD
from palatium_ai.domain.content.citations.models import CitationAnchor
from palatium_ai.domain.content.citations.normalizer import normalize_for_match

#: Closed set (010). ``declared_range`` is the only outcome that trusts an offset, and
#: only after the quote confirmed it; the rest describe *why* there is no highlight.
CitationLocateOutcome = Literal[
    "declared_range",
    "quote_match",
    "ambiguous_quote",
    "quote_not_found",
    "no_text",
]


class CitationLocation(BaseModel):
    """Where the citation sits in the source text — or why that is unknown."""

    model_config = {"frozen": True}

    outcome: CitationLocateOutcome
    #: Absolute offsets in ``safe_text``; both ``None`` when nothing is highlighted.
    start: int | None = None
    end: int | None = None

    @model_validator(mode="after")
    def _span_is_paired(self) -> CitationLocation:
        if (self.start is None) != (self.end is None):
            raise ValueError("citation location needs start and end together")
        if self.start is not None and self.end is not None and (self.start < 0 or self.end <= self.start):
            raise ValueError("citation location must satisfy 0 <= start < end")
        return self

    @property
    def highlighted(self) -> bool:
        return self.start is not None


class CitationWindow(BaseModel):
    """A bounded slice of the source document plus its absolute offsets."""

    model_config = {"frozen": True}

    start: int
    end: int
    text: str


class CitationLocator:
    """Quote-first resolver; no I/O, no model call, fully deterministic (055)."""

    @staticmethod
    def locate(
        *,
        text: str,
        quote: str | None,
        declared_range: tuple[int, int] | None = None,
        anchor: CitationAnchor = "char_location",
    ) -> CitationLocation:
        """Resolve one citation against ``text`` (the source body we sent)."""
        if not text.strip():
            return CitationLocation(outcome="no_text")

        normalized_quote = normalize_for_match(quote or "")
        if not normalized_quote:
            # Nothing to verify against: the client must send the quote, so an empty
            # one is a boundary bug, and "no highlight" is the honest outcome for it.
            return CitationLocation(outcome="quote_not_found")

        declared = declared_range if anchor == "char_location" else None
        if declared is not None and _declared_agrees(text, declared, normalized_quote):
            return CitationLocation(outcome="declared_range", start=declared[0], end=declared[1])

        normalized_text, starts, ends = _normalize_with_offsets(text)
        matches = _occurrences(normalized_text, normalized_quote)
        if len(matches) == 1:
            index = matches[0]
            return CitationLocation(
                outcome="quote_match",
                start=starts[index],
                end=ends[index + len(normalized_quote) - 1],
            )
        if matches:
            return CitationLocation(outcome="ambiguous_quote")
        return CitationLocation(outcome="quote_not_found")


def citation_window(
    text: str,
    *,
    focus: tuple[int, int] | None,
    window_chars: int = CITATION_WINDOW_CHARS,
    pad: int = CITATION_WINDOW_PAD,
) -> CitationWindow:
    """Bounded slice around ``focus`` (or the head when nothing is located).

    A located span always fits: its length is the quote length, capped at
    ``CITATION_QUOTE_MAX_CHARS`` == ``window_chars`` at the request boundary. Should a
    longer span arrive anyway, the slice starts at the span (the highlight is not
    pushed off the left edge) and stays bounded — a response size must not depend on
    how generous a caller was (020).
    """
    length = len(text)
    if length <= window_chars:
        return CitationWindow(start=0, end=length, text=text)
    if focus is None:
        return CitationWindow(start=0, end=window_chars, text=text[:window_chars])

    start = max(0, focus[0] - pad)
    end = min(length, start + window_chars)
    if focus[1] - focus[0] > window_chars:
        start = max(0, min(focus[0], length - window_chars))
        end = min(length, start + window_chars)
    elif end < focus[1]:
        end = min(length, focus[1])
        start = max(0, end - window_chars)
    return CitationWindow(start=start, end=end, text=text[start:end])


def _declared_agrees(text: str, span: tuple[int, int], normalized_quote: str) -> bool:
    """True only when the declared slice and the quote describe the same text.

    Either direction counts: providers that report a wider span (the whole paragraph
    around the quote) are as trustworthy as providers that report the quote itself.
    """
    start, end = span
    if start >= len(text) or end > len(text):
        return False
    sliced = normalize_for_match(text[start:end])
    if not sliced:
        return False
    return normalized_quote in sliced or sliced in normalized_quote


def _occurrences(haystack: str, needle: str) -> list[int]:
    """Normalised offsets of ``needle``; stops at the second match (only uniqueness matters)."""
    found: list[int] = []
    index = haystack.find(needle)
    while index != -1:
        found.append(index)
        if len(found) > 1:
            break
        index = haystack.find(needle, index + 1)
    return found


def _normalize_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    """``normalize_for_match(text)`` plus, per normalised char, its original span.

    Built rather than approximated: mapping a normalised offset back by adding a
    constant is exactly how a highlight lands one word off after a double space.
    """
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            run_end = index + 1
            while run_end < length and text[run_end].isspace():
                run_end += 1
            chars.append(" ")
            starts.append(index)
            ends.append(run_end)
            index = run_end
            continue
        chars.append(char)
        starts.append(index)
        ends.append(index + 1)
        index += 1

    # Collapsing leaves at most one space at each edge, so trimming is a slice —
    # this keeps the result equal to ``normalize_for_match`` by construction.
    if chars and chars[0] == " ":
        chars, starts, ends = chars[1:], starts[1:], ends[1:]
    if chars and chars[-1] == " ":
        chars, starts, ends = chars[:-1], starts[:-1], ends[:-1]
    return "".join(chars), starts, ends


__all__ = [
    "CitationLocateOutcome",
    "CitationLocation",
    "CitationLocator",
    "CitationWindow",
    "citation_window",
]
