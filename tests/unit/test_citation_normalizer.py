"""Provider citations: the anchor a provider gave, never one we invented (W3a).

Three invariants are pinned here, because collapsing any of them silently turns a
"page 2 of the contract" chip into a link to the wrong place:

1. OpenAI-style offsets index the ANSWER; Anthropic offsets index the SOURCE.
2. An unknown position stays ``None`` — never ``0`` and never a clamped span.
3. Every emitted citation is counted, including the dropped ones, so the resolution
   rate cannot be improved by discarding the hard cases.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pydantic import ValidationError

from palatium_ai.domain.content.citations import (
    CitationRef,
    classify,
    normalize_citations,
    normalize_for_match,
)
from palatium_ai.infrastructure.llm.citation_mapping import citations_from_response

ANSWER = "Договор вступает в силу\nс момента подписания сторонами."


def test_frozen_and_serialisable() -> None:
    ref = CitationRef(source_ref="dogovor.pdf", page=2, anchor="page_location")
    with pytest.raises(ValidationError):
        ref.page = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    (
        {"source_ref": "a.pdf", "anchor": "url_only", "page": 1},
        {"source_ref": "a.pdf", "anchor": "char_location", "source_range": (5, 5)},
        {"source_ref": "a.pdf", "anchor": "char_location", "source_range": (-1, 4)},
        {"source_ref": "a.pdf", "anchor": "char_location"},
        {"source_ref": "", "anchor": "url_only"},
    ),
)
def test_invalid_anchor_shapes_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CitationRef(**payload)  # type: ignore[arg-type]


def test_url_only_may_carry_an_answer_range() -> None:
    ref = CitationRef(source_ref="https://example.com", answer_range=(0, 7), anchor="url_only")
    assert ref.answer_range == (0, 7)
    assert ref.source_range is None


def test_whitespace_is_normalised_only_for_matching() -> None:
    assert normalize_for_match("a\n\n b\tc") == "a b c"
    quote = "вступает в силу\nс"
    ref = CitationRef(source_ref="x", quote=quote, anchor="char_location", source_range=(0, 3))
    assert classify(ref, ANSWER) == "resolved"
    assert ref.quote == quote, "the stored quote must stay exactly as the provider gave it"


def test_answer_range_past_the_answer_is_out_of_range() -> None:
    ref = CitationRef(source_ref="x", answer_range=(0, len(ANSWER) + 1), anchor="url_only")
    assert classify(ref, ANSWER) == "out_of_range"


def test_quote_the_answer_never_contained_is_unanchored() -> None:
    ref = CitationRef(source_ref="x", quote="этого нет в ответе", anchor="char_location", source_range=(0, 2))
    assert classify(ref, ANSWER) == "unanchored"


def test_out_of_range_wins_over_unanchored() -> None:
    """A citation that points past the end has no answer text to search in."""
    ref = CitationRef(source_ref="x", quote="нет", answer_range=(500, 600), anchor="url_only")
    assert classify(ref, ANSWER) == "out_of_range"


def test_normalize_dedupes_but_counts_every_emitted_citation() -> None:
    ref = CitationRef(source_ref="a.pdf", answer_range=(0, 7), anchor="url_only")
    other = CitationRef(source_ref="a.pdf", answer_range=(0, 8), anchor="url_only")
    bad = CitationRef(source_ref="b.pdf", quote="нет в ответе", anchor="url_only")

    report = normalize_citations([ref, ref, other, bad], answer_text=ANSWER)

    assert report.resolved == (ref, other)
    assert report.emitted == 4, "duplicates still count as emitted"
    assert len(report.outcomes) == 4
    assert report.unanchored == 1


def test_cap_keeps_document_order() -> None:
    citations = [CitationRef(source_ref=f"f{i}.pdf", answer_range=(i, i + 1), anchor="url_only") for i in range(40)]
    report = normalize_citations(citations, answer_text="x" * 100)
    assert len(report.resolved) <= 32
    assert [ref.source_ref for ref in report.resolved] == [f"f{i}.pdf" for i in range(len(report.resolved))]


def test_openai_annotation_offsets_are_answer_positions() -> None:
    """The original plan's bug: ``start_index`` is the answer, not the source."""
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=ANSWER,
                    annotations=[
                        SimpleNamespace(type="url_citation", url="https://ea.iba/x", title="Договор", start_index=0, end_index=7),
                    ],
                )
            )
        ]
    )

    (citation,) = citations_from_response(response)

    assert citation.anchor == "url_only"
    assert citation.answer_range == (0, 7)
    assert citation.source_range is None, "an answer offset must never be stored as a source offset"
    assert citation.source_ref == "https://ea.iba/x"


def test_anthropic_char_citation_is_a_source_position() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="text",
                            text="…",
                            citations=[
                                SimpleNamespace(
                                    type="char_location",
                                    cited_text="вступает в силу",
                                    document_title="dogovor.pdf",
                                    start_char_index=10,
                                    end_char_index=26,
                                )
                            ],
                        )
                    ]
                )
            )
        ]
    )

    (citation,) = citations_from_response(response)

    assert citation.anchor == "char_location"
    assert citation.source_range == (10, 26)
    assert citation.answer_range is None
    assert citation.quote == "вступает в силу"


def test_anthropic_page_citation_keeps_the_page_unknown_when_absent() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": [{"citations": [{"type": "page_location", "document_title": "act.pdf", "cited_text": "п. 4"}]}]
                }
            }
        ]
    }

    (citation,) = citations_from_response(response)

    assert citation.anchor == "page_location"
    assert citation.page is None, "a missing page must stay unknown, not become 1"


def test_citation_without_a_user_facing_source_is_skipped() -> None:
    response = {"choices": [{"message": {"content": [{"citations": [{"type": "char_location", "document_index": 0}]}]}}]}
    assert citations_from_response(response) == ()


def test_no_citations_is_an_honest_empty() -> None:
    assert citations_from_response(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])) == ()
    assert citations_from_response(SimpleNamespace(choices=[])) == ()
