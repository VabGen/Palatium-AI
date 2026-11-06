# src/palatium_ai/domain/content/citations/markers.py

"""Keep resolvable ``[n]`` markers in prose for the UI citation chips (pure, no I/O).

Big Tech answers (Perplexity / Claude / Copilot) put the source next to the claim.
``meta.source_refs`` remains the structured list; the marker is the in-prose handle
the client turns into a clickable chip. Stripping resolvable markers used to leave
only a footer — that is filing, not grounding.

Dangling markers (``n`` outside ``1..source_count``) are left untouched for the
``dangling_citation`` lint. Markdown links ``[1](url)`` are never treated as cites.
"""

from __future__ import annotations

import re

from palatium_ai.domain.content.content_document import ContentDocument

#: ``[12]`` not followed by ``(`` — a markdown link ``[1](url)`` is a real control.
_MARKER_RE = re.compile(r"\[(\d{1,2})\](?!\()")

__all__ = ["strip_citation_markers", "CITATION_MARKER_RE"]

#: Re-export for clients that want the same pattern as the server.
CITATION_MARKER_RE = _MARKER_RE


def strip_citation_markers(document: ContentDocument, *, source_count: int) -> ContentDocument:
    """Identity for resolvable cites — markers stay for the UI (wave: inline chips).

    Kept as a named gate so call sites and tests do not grow a second decision about
    whether to mutate the document. ``source_count`` is accepted for ABI stability.
    """
    _ = source_count
    return document
