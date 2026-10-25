# src/palatium_ai/core/types/citations.py

"""Bounds for source-citation highlighting (W3b-2), declared once (010).

The endpoint returns a *window* of the source document, never the document: without a
ceiling it would be a download path that bypasses ``issue_download`` and its presigned
URL (020). Sizes live here rather than in the router so that the service, the tests and
the UI budget all read the same number (050: no magic numbers).
"""

from __future__ import annotations

#: Characters of source text returned around the located span (and as the head
#: window when nothing could be located).
CITATION_WINDOW_CHARS = 2000
#: Context kept before the span inside the window, so the highlight is not glued to
#: the left edge of the returned fragment.
CITATION_WINDOW_PAD = 300
#: Longest quote accepted from the client. A provider quote is a sentence or two;
#: the cap keeps the deterministic search bounded (and matches the window, so a
#: verified quote can always be shown in full).
CITATION_QUOTE_MAX_CHARS = 2000

__all__ = ["CITATION_QUOTE_MAX_CHARS", "CITATION_WINDOW_CHARS", "CITATION_WINDOW_PAD"]
