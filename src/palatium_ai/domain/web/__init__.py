# src/palatium_ai/domain/web/__init__.py

"""Web search domain contracts (070 ``web_fallback``)."""

from palatium_ai.domain.web.port import WebSearchPort
from palatium_ai.domain.web.types import WebSearchHit, WebSearchQuery, WebSearchResult

__all__ = ["WebSearchHit", "WebSearchPort", "WebSearchQuery", "WebSearchResult"]
