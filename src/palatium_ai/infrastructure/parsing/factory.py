# src/palatium_ai/infrastructure/parsing/factory.py

"""DocumentParserPort factory.

Optional parsers are registered only when their library is importable, so a lean
install degrades to "this media type cannot be parsed yet" (an explicit,
fail-closed rejection at intake) instead of an ImportError deep inside a request.
"""

from __future__ import annotations

import importlib.util

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.ports.document_parser import DocumentParserPort
from palatium_ai.infrastructure.parsing.document_parser import (
    CompositeDocumentParser,
    DocxParser,
    PdfParser,
    PlainTextParser,
)

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

_TEXT_MEDIA_TYPES = ("text/plain", "text/markdown", "text/csv")

# MIME -> importable module name of the extra that provides the matching parser.
# This is the *module* name, not the distribution name: ``importlib.util.find_spec``
# resolves modules, and ``python-docx`` installs ``docx`` (a distribution name
# with a dash is not importable, so the probe would always miss).
_OPTIONAL_PARSERS: tuple[tuple[str, str], ...] = (
    ("application/pdf", "pypdf"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
)


def _module_available(module_name: str) -> bool:
    """Whether a distribution is importable, without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except ImportError, ValueError:
        return False


def build_document_parser(settings: Settings) -> DocumentParserPort:
    """Build the composite parser with the limits from configuration."""
    config = settings.attachments
    parsers: list[DocumentParserPort] = [
        PlainTextParser(media_types=_TEXT_MEDIA_TYPES, max_chars=config.max_parsed_chars),
    ]
    rejected: list[str] = []

    for mime_type, module_name in _OPTIONAL_PARSERS:
        if not _module_available(module_name):
            rejected.append(mime_type)
            logger.warning(
                "Attachment parser unavailable; media type will be rejected at intake",
                mime_type=mime_type,
                package=module_name,
            )
            continue
        if mime_type == "application/pdf":
            parsers.append(PdfParser(max_chars=config.max_parsed_chars, max_pages=config.max_parsed_pages))
        else:
            parsers.append(DocxParser(max_chars=config.max_parsed_chars))

    logger.info("DocumentParserPort: local", parsers=len(parsers), rejected_media_types=rejected)
    return CompositeDocumentParser(parsers)
