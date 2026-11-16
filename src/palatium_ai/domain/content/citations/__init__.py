# src/palatium_ai/domain/content/citations/__init__.py

"""Provider-neutral citations: model, resolver, source locator (W3a, W3b-2).

The model and the resolver make the data honest (W3a). ``CitationLocator`` answers one
narrow question for the UI: *where in the source text we sent does this citation sit* —
and answers "unknown" when the quote does not settle it (W3b-2).
"""

from palatium_ai.domain.content.citations.locate import (
    CitationLocateOutcome,
    CitationLocation,
    CitationLocator,
    CitationWindow,
    citation_window,
)
from palatium_ai.domain.content.citations.models import CitationAnchor, CitationRef
from palatium_ai.domain.content.citations.normalizer import (
    CitationOutcome,
    NormalizedCitations,
    classify,
    normalize_citations,
    normalize_for_match,
)

__all__ = [
    "CitationAnchor",
    "CitationLocateOutcome",
    "CitationLocation",
    "CitationLocator",
    "CitationOutcome",
    "CitationRef",
    "CitationWindow",
    "NormalizedCitations",
    "citation_window",
    "classify",
    "normalize_citations",
    "normalize_for_match",
]
