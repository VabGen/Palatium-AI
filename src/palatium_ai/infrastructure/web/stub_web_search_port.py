# src/palatium_ai/infrastructure/web/stub_web_search_port.py

"""Stub WebSearchPort — empty hits when live HTTP is disabled."""

from __future__ import annotations

from palatium_ai.domain.web.types import WebSearchQuery, WebSearchResult


class StubWebSearchPort:
    """Deterministic no-op search for tests / default prod-safe mode."""

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        _ = query
        return WebSearchResult(
            hits=(),
            hit_count=0,
            provider="stub",
            note="web_fallback stub — local knowledge/memory returned empty; live fetch not wired",
        )
