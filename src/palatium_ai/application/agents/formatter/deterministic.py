# src/palatium_ai/application/agents/formatter/deterministic.py

"""Deterministic ContentDocument emit from ready source (emergency / hop soft-degrade).

Presentation (icons, sections, brand) belongs to the Formatter LLM path.
This module only blockifies cleaned prose when budget forbids an LLM call.
"""

from __future__ import annotations

from typing import Literal

from palatium_ai.application.agents.formatter.cleanup import mechanical_cleanup
from palatium_ai.application.agents.formatter.config import (
    FORMATTER_FAST_PATH_CONFIDENCE,
    FORMATTER_SOURCE_MAX_CHARS,
)
from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.content_document import DocumentMeta
from palatium_ai.domain.content.markdown_blocks import prose_to_blocks
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

EmitMode = Literal["deterministic_blockify", "passthrough_paragraph"]

# Re-export for callers that imported cleanup from this module.
__all__ = [
    "aligned_document_from_source",
    "document_from_source_content",
    "mechanical_cleanup",
]


def document_from_source_content(
    source: str,
    *,
    task_input: FormatterInput,
    confidence: float = FORMATTER_FAST_PATH_CONFIDENCE,
) -> ContentDocument:
    """Emit a ContentDocument from ready source text (no LLM)."""
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    text = mechanical_cleanup(source).strip() or " "
    title, blocks = prose_to_blocks(text, max_paragraph_chars=FORMATTER_SOURCE_MAX_CHARS)
    return ContentDocument(
        schema_version=1,
        locale=locale,
        title=title,
        blocks=blocks,
        actions=(),
        meta=DocumentMeta(
            confidence=confidence,
            requires_review=task_input.requires_review,
            source_refs=(),
            interaction="none",
        ),
    )


def aligned_document_from_source(
    source: str,
    *,
    task_input: FormatterInput,
    confidence: float = FORMATTER_FAST_PATH_CONFIDENCE,
) -> tuple[ContentDocument, EmitMode]:
    """Build + meta-align document; report whether structure beyond paragraphs was used."""
    document = align_formatter_meta(
        document_from_source_content(source, task_input=task_input, confidence=confidence),
        task_input,
    )
    mode: EmitMode = (
        "passthrough_paragraph"
        if all(block.type == "paragraph" for block in document.blocks) and document.title is None
        else "deterministic_blockify"
    )
    return document, mode
