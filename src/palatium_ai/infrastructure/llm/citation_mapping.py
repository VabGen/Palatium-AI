# src/palatium_ai/infrastructure/llm/citation_mapping.py

"""Decode provider citation payloads into the provider-neutral ``CitationRef`` (W3a).

Two shapes exist in the wild and they disagree about what a position means:

* OpenAI-style annotations (``message.annotations[].type == "url_citation"``):
  ``start_index``/``end_index`` index the **answer** the model produced.
* Anthropic document citations (content blocks with ``type == "char_location"`` /
  ``page_location`` / ``content_block_location``): ``start_char_index``,
  ``start_page_number``, ``start_block_index`` index the **source document**.

Mapping both onto one field is how "page 2 of the contract" turns into "character 480
of the answer". Each shape is decoded here, once, with the coordinate space stated in
the code; anything unrecognised is skipped rather than guessed (050).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.content.citations import CitationRef

logger = get_logger(__name__)

_OPENAI_URL_CITATION = "url_citation"
_ANTHROPIC_ANCHORS = ("char_location", "page_location", "content_block_location")
_MAX_DECODED = 32


def citations_from_response(response: object) -> tuple[CitationRef, ...]:
    """Every citation attached to a non-streamed completion, in provider order."""
    message = _first_message(response)
    if message is None:
        return ()
    found = [
        *_from_openai_annotations(_as_list(_get(message, "annotations"))),
        *_from_anthropic_blocks(_as_list(_get(message, "content"))),
    ]
    return tuple(found[:_MAX_DECODED])


def _first_message(response: object) -> object | None:
    choices = _as_list(_get(response, "choices"))
    if not choices:
        return None
    return _get(choices[0], "message")


def _from_openai_annotations(annotations: Iterable[object]) -> list[CitationRef]:
    out: list[CitationRef] = []
    for raw in annotations:
        if _get(raw, "type") != _OPENAI_URL_CITATION:
            continue
        url = _text(_get(raw, "url"))
        if not url:
            continue
        out.append(
            CitationRef(
                source_ref=url,
                quote=_text(_get(raw, "title")) or None,
                answer_range=_span(_get(raw, "start_index"), _get(raw, "end_index")),
                anchor="url_only",
            ),
        )
    return out


def _from_anthropic_blocks(blocks: Iterable[object]) -> list[CitationRef]:
    out: list[CitationRef] = []
    for block in blocks:
        for raw in _as_list(_get(block, "citations")):
            citation = _anthropic_citation(raw)
            if citation is not None:
                out.append(citation)
    return out


def _anthropic_citation(raw: object) -> CitationRef | None:
    anchor = _get(raw, "type")
    if not isinstance(anchor, str) or anchor not in _ANTHROPIC_ANCHORS:
        return None
    source = _text(_get(raw, "document_title")) or _text(_get(raw, "source")) or _text(_get(raw, "url"))
    if not source:
        # A citation to an unnamed document cannot be shown or opened; the internal
        # document_index is not a user-facing label (050: no invented labels).
        return None
    quote = _text(_get(raw, "cited_text")) or None
    if anchor == "page_location":
        page = _get(raw, "start_page_number")
        return CitationRef(
            source_ref=source,
            quote=quote,
            page=page if isinstance(page, int) and page >= 1 else None,
            anchor="page_location",
        )
    if anchor == "content_block_location":
        blocks = _span(_get(raw, "start_block_index"), _get(raw, "end_block_index"))
        return CitationRef(source_ref=source, quote=quote, source_range=blocks, anchor="content_block_location")
    return CitationRef(
        source_ref=source,
        quote=quote,
        source_range=_span(_get(raw, "start_char_index"), _get(raw, "end_char_index")),
        anchor="char_location",
    )


def _span(start: object, end: object) -> tuple[int, int] | None:
    """A valid ``(start, end)`` pair, or None — never a clamped or zero-filled span."""
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 0 or end <= start:
        return None
    return (start, end)


def _get(obj: object, name: str) -> object | None:
    """Attribute or key access: LiteLLM yields pydantic objects, gateways yield dicts."""
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _as_list(value: object) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    return []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["citations_from_response"]
