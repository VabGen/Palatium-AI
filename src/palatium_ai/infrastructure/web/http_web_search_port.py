# src/palatium_ai/infrastructure/web/http_web_search_port.py

"""HTTP-backed WebSearchPort for ``web_fallback`` (070) with retry + circuit (020)."""

from __future__ import annotations

import time

from typing import Protocol

import httpx

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.resilience.circuit import ConsecutiveFailureCircuit
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.domain.web.types import WebSearchHit, WebSearchQuery, WebSearchResult

_CIRCUIT_TARGET = "web_fallback"


class WebSearchTransport(Protocol):
    """Minimal async search surface (injectable in tests)."""

    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        """Return raw hit dicts with title/url/snippet/score keys."""

    async def aclose(self) -> None:
        """Close HTTP client resources."""


def _is_transient_web_http_error(exc: BaseException) -> bool:
    """Retry transport failures and upstream 5xx; never retry auth/client 4xx."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class DuckDuckGoInstantAnswerTransport:
    """DuckDuckGo Instant Answer JSON API — no API key required."""

    _ENDPOINT = "https://api.duckduckgo.com/"

    def __init__(self, *, timeout_seconds: float = 15.0, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        response = await self._client.get(
            self._ENDPOINT,
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        hits: list[dict[str, object]] = []
        abstract = str(payload.get("AbstractText", "")).strip()
        abstract_url = str(payload.get("AbstractURL", "")).strip()
        heading = str(payload.get("Heading", "")).strip() or query
        if abstract:
            hits.append(
                {
                    "title": heading[:500],
                    "url": abstract_url[:2000],
                    "snippet": abstract[:2000],
                    "score": 0.75,
                }
            )
        related = payload.get("RelatedTopics")
        if isinstance(related, list):
            for item in related:
                if len(hits) >= max_results:
                    break
                if not isinstance(item, dict):
                    continue
                text = str(item.get("Text", "")).strip()
                url = str(item.get("FirstURL", "")).strip()
                if not text:
                    continue
                hits.append(
                    {
                        "title": text[:120],
                        "url": url[:2000],
                        "snippet": text[:2000],
                        "score": 0.55,
                    }
                )
        return hits[:max_results]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class BraveSearchTransport:
    """Brave Search API (requires WEB_FALLBACK_API_KEY)."""

    _ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            msg = "Brave search requires WEB_FALLBACK_API_KEY"
            raise ValueError(msg)
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        response = await self._client.get(
            self._ENDPOINT,
            params={"q": query, "count": str(max_results)},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        web = payload.get("web")
        results = web.get("results") if isinstance(web, dict) else None
        if not isinstance(results, list):
            return []
        hits: list[dict[str, object]] = []
        for index, item in enumerate(results[:max_results]):
            if not isinstance(item, dict):
                continue
            hits.append(
                {
                    "title": str(item.get("title", ""))[:500],
                    "url": str(item.get("url", ""))[:2000],
                    "snippet": str(item.get("description", ""))[:2000],
                    "score": max(0.0, min(1.0, 0.9 - index * 0.05)),
                }
            )
        return hits

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class HttpWebSearchPort:
    """Execute external web search via injectable transport; scan snippets (020)."""

    def __init__(
        self,
        transport: WebSearchTransport,
        *,
        provider: str,
        circuit: ConsecutiveFailureCircuit | None = None,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        self._transport = transport
        self._provider = provider
        self._circuit = circuit or ConsecutiveFailureCircuit()
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay_seconds = max(0.1, retry_delay_seconds)

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        now = time.monotonic()
        if not self._circuit.allow_request(now):
            agent_metrics.record_circuit_state(_CIRCUIT_TARGET, self._circuit.state_code())
            retry_after = max(0.0, self._circuit.open_until - now)
            return WebSearchResult(
                hits=(),
                hit_count=0,
                provider=self._provider,
                note=f"web_fallback circuit open (retry after ~{retry_after:.0f}s)",
            )

        try:
            raw_hits = await self._fetch_with_retry(query=query.query, max_results=query.max_results)
        except httpx.HTTPError as exc:
            self._circuit.record_failure(time.monotonic())
            agent_metrics.record_circuit_state(_CIRCUIT_TARGET, self._circuit.state_code())
            return WebSearchResult(
                hits=(),
                hit_count=0,
                provider=self._provider,
                note=f"web_fallback HTTP error: {type(exc).__name__}",
            )

        self._circuit.record_success()
        agent_metrics.record_circuit_state(_CIRCUIT_TARGET, self._circuit.state_code())

        hits: list[WebSearchHit] = []
        for raw in raw_hits[: query.max_results]:
            title = str(raw.get("title", ""))[:500]
            url = str(raw.get("url", ""))[:2000]
            snippet = str(raw.get("snippet", ""))[:2000]
            try:
                scan_text(f"{title}\n{snippet}", field="web_fallback_hit")
            except SecretScanError:
                continue
            score_raw = raw.get("score", 0.5)
            try:
                score = float(score_raw)  # type: ignore[arg-type]
            except TypeError, ValueError:
                score = 0.5
            hits.append(
                WebSearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=max(0.0, min(1.0, score)),
                )
            )
        return WebSearchResult(
            hits=tuple(hits),
            hit_count=len(hits),
            provider=self._provider,
            note="" if hits else "web_fallback live search returned no hits",
        )

    async def _fetch_with_retry(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(
                multiplier=self._retry_delay_seconds,
                min=self._retry_delay_seconds,
                max=max(self._retry_delay_seconds, 4.0),
            ),
            retry=retry_if_exception(_is_transient_web_http_error),
            reraise=True,
        ):
            with attempt:
                return await self._transport.fetch_hits(query=query, max_results=max_results)
        msg = "web_fallback retry loop exited without result"
        raise RuntimeError(msg)

    async def aclose(self) -> None:
        await self._transport.aclose()
