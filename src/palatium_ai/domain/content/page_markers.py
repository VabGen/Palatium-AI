# src/palatium_ai/domain/content/page_markers.py

"""Internal page-addressing markers in extracted attachment text.

The parser addresses pages so a citation can be traced back to a page, and it
writes the address as ``[[page N]]`` inline. That marker is *navigation for us*,
not content: handed to a model it is copied into the user's answer verbatim, and
the user reads ``[[page 1]]`` as a defect (it is one — the seam leaked).

Producer (``ParsedDocument.text``) and the user-facing guard
(``InternalVocabularyPolicy``) import this module, so the format has exactly one
owner and cannot drift (010, 050).
"""

from __future__ import annotations

import re

#: How a page address is rendered into extracted text.
PAGE_MARKER_TEMPLATE = "[[page {number}]]"

#: One marker, optionally the model's single-bracket echo (``[page 1]``) or
#: surrounding spaces. ``page`` is required, so a citation like ``[1]`` is never
#: touched — only our own addressing vocabulary is.
PAGE_MARKER_RE = re.compile(r"[ \t]*\[\[?[ \t]*page[ \t]*\d+[ \t]*\]\]?", re.IGNORECASE)

#: A marker alone on its line takes the line with it — removing only the marker
#: would leave a blank line in the middle of the answer.
PAGE_MARKER_LINE_RE = re.compile(r"^[ \t]*\[\[?[ \t]*page[ \t]*\d+[ \t]*\]\]?[ \t]*\n?", re.IGNORECASE | re.MULTILINE)
#: Only applied after a marker line was removed: the marker's own blank line goes
#: with it instead of turning one paragraph break into three.
_BLANK_LINE_RUN_RE = re.compile(r"\n{3,}")

#: A trailing fragment of a marker that has not arrived completely yet; a token
#: stream must hold it instead of painting ``[[pa`` and then deleting it (020).
PAGE_MARKER_TAIL_RE = re.compile(r"\[\[?[ \t]*(?:p(?:a(?:g(?:e)?)?)?)?[ \t]*\d*[ \t]*\]{0,2}$", re.IGNORECASE)

#: A complete citation token (``[1]``) ends the same way and is NOT a page marker:
#: holding it would delay a legit source reference for no reason.
_CITATION_RE = re.compile(r"\[\d+\]")

#: Longest possible marker fragment held across a chunk boundary.
MAX_PAGE_MARKER_TAIL = len("[[page 999999]]")


def strip_page_markers(text: str) -> str:
    """Remove page addresses from user-facing text; untouched when none present."""
    if "[" not in text:
        return text
    cleaned = PAGE_MARKER_LINE_RE.sub("", text)
    inline = PAGE_MARKER_RE.sub("", cleaned)
    if inline == text:
        return text
    return _BLANK_LINE_RUN_RE.sub("\n\n", inline).lstrip("\n")


def page_marker_hold_start(text: str) -> int:
    """Index from which ``text`` is held because it may end mid-marker.

    Returns ``len(text)`` when the whole buffer is safe to paint.
    """
    window = text[-MAX_PAGE_MARKER_TAIL:]
    earliest = len(text)
    for match in PAGE_MARKER_TAIL_RE.finditer(window):
        fragment = match.group(0)
        if _CITATION_RE.fullmatch(fragment.strip()):
            continue
        earliest = min(earliest, len(text) - (len(window) - match.start()))
    return earliest


__all__ = [
    "MAX_PAGE_MARKER_TAIL",
    "PAGE_MARKER_LINE_RE",
    "PAGE_MARKER_RE",
    "PAGE_MARKER_TEMPLATE",
    "page_marker_hold_start",
    "strip_page_markers",
]
