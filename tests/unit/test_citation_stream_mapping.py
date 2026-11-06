"""Provider citation payloads → CitationRef (stream + response)."""

from __future__ import annotations

from palatium_ai.infrastructure.llm.citation_mapping import (
    citations_from_response,
    citations_from_stream_chunk,
)


def test_openai_url_citation_from_stream_delta() -> None:
    chunk = {
        "choices": [
            {
                "delta": {
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://example.com/doc",
                            "title": "Example",
                            "start_index": 0,
                            "end_index": 12,
                        }
                    ]
                }
            }
        ]
    }
    refs = citations_from_stream_chunk(chunk)
    assert len(refs) == 1
    assert refs[0].source_ref == "https://example.com/doc"
    assert refs[0].answer_range == (0, 12)
    assert refs[0].anchor == "url_only"


def test_anthropic_char_location_from_response() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Answer.",
                            "citations": [
                                {
                                    "type": "char_location",
                                    "document_title": "report.pdf",
                                    "cited_text": "Payment terms",
                                    "start_char_index": 10,
                                    "end_char_index": 23,
                                }
                            ],
                        }
                    ]
                }
            }
        ]
    }
    refs = citations_from_response(response)
    assert len(refs) == 1
    assert refs[0].source_ref == "report.pdf"
    assert refs[0].source_range == (10, 23)
    assert refs[0].anchor == "char_location"
    assert refs[0].quote == "Payment terms"


def test_unnamed_anthropic_citation_is_skipped() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {
                            "citations": [
                                {
                                    "type": "char_location",
                                    "start_char_index": 0,
                                    "end_char_index": 4,
                                }
                            ]
                        }
                    ]
                }
            }
        ]
    }
    assert citations_from_response(response) == ()
