"""Unit tests for WebSearchPort (stub + HTTP transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from palatium_ai.core.config.settings import Settings
from palatium_ai.core.resilience.circuit import ConsecutiveFailureCircuit
from palatium_ai.domain.web.types import WebSearchQuery
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.web.factory import build_web_search_port
from palatium_ai.infrastructure.web.http_web_search_port import HttpWebSearchPort
from palatium_ai.infrastructure.web.stub_web_search_port import StubWebSearchPort


class _FakeWebTransport:
    def __init__(self, hits: list[dict[str, object]] | None = None) -> None:
        self.hits = hits or [
            {
                "title": "Palatium AI",
                "url": "https://example.com/palatium",
                "snippet": "Layered agent platform with MCP tools.",
                "score": 0.8,
            }
        ]
        self.closed = False
        self.calls = 0

    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        _ = query
        self.calls += 1
        return self.hits[:max_results]

    async def aclose(self) -> None:
        self.closed = True


class _FlakyWebTransport(_FakeWebTransport):
    """Fails with ConnectError for the first ``fail_times`` calls, then succeeds."""

    def __init__(self, *, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times

    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ConnectError("simulated upstream outage")
        return self.hits[:max_results]


class _AlwaysFailTransport(_FakeWebTransport):
    async def fetch_hits(self, *, query: str, max_results: int) -> list[dict[str, object]]:
        _ = query, max_results
        self.calls += 1
        raise httpx.ConnectError("always down")


@pytest.mark.asyncio
async def test_stub_web_search_returns_empty_tagged_note() -> None:
    port = StubWebSearchPort()
    result = await port.search(WebSearchQuery(user_id="u1", query="architecture", max_results=3))
    assert result.hit_count == 0
    assert result.provider == "stub"
    assert "stub" in result.note


@pytest.mark.asyncio
async def test_http_web_search_port_maps_hits() -> None:
    transport = _FakeWebTransport()
    port = HttpWebSearchPort(transport, provider="ddg")
    result = await port.search(WebSearchQuery(user_id="u1", query="Palatium", max_results=5))
    assert result.hit_count == 1
    assert result.hits[0].title == "Palatium AI"
    assert result.provider == "ddg"
    await port.aclose()
    assert transport.closed is True


@pytest.mark.asyncio
async def test_http_web_search_skips_secret_snippets() -> None:
    transport = _FakeWebTransport(
        hits=[
            {
                "title": "leak",
                "url": "https://example.com",
                "snippet": "api key sk-abcdefghijklmnopqrstuvwxyz012345",
                "score": 0.9,
            },
            {
                "title": "safe",
                "url": "https://example.com/ok",
                "snippet": "No secrets here.",
                "score": 0.7,
            },
        ]
    )
    port = HttpWebSearchPort(transport, provider="ddg")
    result = await port.search(WebSearchQuery(user_id="u1", query="keys", max_results=5))
    assert result.hit_count == 1
    assert result.hits[0].title == "safe"


@pytest.mark.asyncio
async def test_http_web_search_retries_transient_errors() -> None:
    transport = _FlakyWebTransport(fail_times=2)
    port = HttpWebSearchPort(
        transport,
        provider="ddg",
        retry_attempts=3,
        retry_delay_seconds=0.01,
    )
    result = await port.search(WebSearchQuery(user_id="u1", query="retry", max_results=3))
    assert result.hit_count == 1
    assert transport.calls == 3


@pytest.mark.asyncio
async def test_http_web_search_circuit_opens_after_failures() -> None:
    circuit = ConsecutiveFailureCircuit(failures_to_open=2, open_seconds=60.0)
    transport = _AlwaysFailTransport()
    port = HttpWebSearchPort(
        transport,
        provider="ddg",
        circuit=circuit,
        retry_attempts=1,
        retry_delay_seconds=0.01,
    )
    query = WebSearchQuery(user_id="u1", query="down", max_results=3)
    first = await port.search(query)
    second = await port.search(query)
    assert first.hit_count == 0
    assert "HTTP error" in first.note
    assert second.hit_count == 0
    assert "HTTP error" in second.note
    blocked = await port.search(query)
    assert blocked.hit_count == 0
    assert "circuit open" in blocked.note
    assert transport.calls == 2


def test_build_web_search_port_defaults_to_stub() -> None:
    port = build_web_search_port(Settings())
    assert isinstance(port, StubWebSearchPort)


@pytest.mark.asyncio
async def test_platform_web_fallback_uses_injected_port() -> None:
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        web_search_port=HttpWebSearchPort(_FakeWebTransport(), provider="ddg"),
    )
    result = await handler.call_tool(
        "web_fallback",
        {"user_id": "user-1", "query": "Palatium architecture", "max_results": "3"},
    )
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["source"] == "web"
    assert payload["reliability"] == "external_unverified"
    assert payload["provider"] == "ddg"
    assert payload["hit_count"] == 1
    assert payload["hits"][0]["source"] == "web"


@pytest.mark.asyncio
async def test_platform_web_fallback_without_port_errors() -> None:
    handler = PlatformToolHandler(knowledge_port=InMemoryKnowledgePort())
    result = await handler.call_tool(
        "web_fallback",
        {"user_id": "user-1", "query": "Palatium architecture", "max_results": "3"},
    )
    assert result.is_error is True
