# src/palatium_ai/domain/web/port.py

"""WebSearchPort — external read for ``web_fallback`` (070)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.web.types import WebSearchQuery, WebSearchResult


class WebSearchPort(Protocol):
    """Execute external web search; implementations never write."""

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        """Return tagged external hits (empty list is a valid outcome)."""
