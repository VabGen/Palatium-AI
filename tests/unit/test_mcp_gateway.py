# tests/unit/test_mcp_gateway.py

"""Phase 6: MCP gateway pin allowlist stays aligned with Host PlatformToolPin."""

from __future__ import annotations

import importlib.util
import sys

from pathlib import Path
from types import SimpleNamespace

import pytest

from palatium_ai.domain.mcp.tool_policy import pinned_tool_names

_REPO = Path(__file__).resolve().parents[2]
_GATEWAY = _REPO / "mcp_servers" / "gateway"


def _load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pin_allowlist() -> object:
    return _load("gateway_pin_allowlist", _GATEWAY / "pin_allowlist.py")


@pytest.fixture(scope="module")
def upstream_policy() -> object:
    return _load("gateway_upstream_policy", _GATEWAY / "upstream_policy.py")


@pytest.fixture(scope="module")
def pin_filter() -> object:
    # pin_filter imports fastmcp — the package layout keeps `mcp_servers` importable
    # without putting sub-dirs on sys.path (which would shadow stdlib `platform`).
    return _load("gateway_pin_filter", _GATEWAY / "pin_filter.py")


def test_upstream_policy_accepts_loopback_and_compose_http(upstream_policy: object) -> None:
    assert_fn = upstream_policy.assert_upstream_url_safe  # type: ignore[attr-defined]
    for url in (
        "http://127.0.0.1:8080",
        "http://localhost:8080/",
        "http://mcp-edms:8080",
        "https://mcp.internal.example:8443",
    ):
        assert assert_fn(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    (
        "file:///etc/passwd",
        "http://evil.example.com:8080",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal",
        "http://user:pass@127.0.0.1:8080",
        "ftp://127.0.0.1:8080",
    ),
)
def test_upstream_policy_rejects_ssrf_pivots(upstream_policy: object, url: str) -> None:
    assert_fn = upstream_policy.assert_upstream_url_safe  # type: ignore[attr-defined]
    with pytest.raises(upstream_policy.UnsafeUpstreamUrlError):  # type: ignore[attr-defined]
        assert_fn(url)


def test_upstream_policy_env_allowlist_overrides_defaults(
    upstream_policy: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_UPSTREAM_HTTP_ALLOWED_HOSTS", "mcp-edms, internal-dns")
    hosts = upstream_policy.env_http_allowed_hosts()  # type: ignore[attr-defined]
    assert hosts == frozenset({"mcp-edms", "internal-dns"})
    assert upstream_policy.assert_env_upstream_url_safe("http://internal-dns:9000")  # type: ignore[attr-defined]
    with pytest.raises(upstream_policy.UnsafeUpstreamUrlError):  # type: ignore[attr-defined]
        upstream_policy.assert_env_upstream_url_safe("http://analytics:9000")  # type: ignore[attr-defined]


def test_gateway_allowlist_matches_host_pins(pin_allowlist: object) -> None:
    catalog = pin_allowlist.GATEWAY_PINNED_TOOLS  # type: ignore[attr-defined]
    assert set(catalog) == {"edms", "analytics"}
    assert "platform" not in catalog
    for server, tools in catalog.items():
        assert frozenset(tools) == pinned_tool_names(server)


def test_gateway_rejects_platform_server(pin_allowlist: object) -> None:
    with pytest.raises(ValueError, match="platform"):
        pin_allowlist.allowlist_for("platform")  # type: ignore[attr-defined]


@pytest.mark.asyncio()
async def test_pin_filter_strips_unpinned_tools(pin_filter: object) -> None:
    mw_cls = pin_filter.PinAllowlistMiddleware  # type: ignore[attr-defined]
    mw = mw_cls({"search_documents", "archive_document"})

    tools = [
        SimpleNamespace(name="search_documents"),
        SimpleNamespace(name="evil_exfiltrate"),
        SimpleNamespace(name="archive_document"),
    ]

    async def _next(_ctx: object) -> list[object]:
        return tools

    filtered = await mw.on_list_tools(SimpleNamespace(), _next)
    assert [t.name for t in filtered] == ["search_documents", "archive_document"]


@pytest.mark.asyncio()
async def test_pin_filter_blocks_unpinned_call(pin_filter: object) -> None:
    from fastmcp.exceptions import ToolError

    mw_cls = pin_filter.PinAllowlistMiddleware  # type: ignore[attr-defined]
    mw = mw_cls({"search_documents"})

    async def _next(_ctx: object) -> str:
        return "ok"

    ctx = SimpleNamespace(message=SimpleNamespace(name="evil_exfiltrate"))
    with pytest.raises(ToolError, match="pin allowlist"):
        await mw.on_call_tool(ctx, _next)

    ok_ctx = SimpleNamespace(message=SimpleNamespace(name="search_documents"))
    assert await mw.on_call_tool(ok_ctx, _next) == "ok"


def test_build_gateway_constructs_without_upstream_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proxy is lazy — build must not require a live upstream (FastMCP docs)."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "phase6-gateway-token")
    monkeypatch.delenv("MCP_ALLOW_ANON", raising=False)
    monkeypatch.delenv("MCP_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    for mod in ("mcp_servers.gateway.gateway_mcp_server", "mcp_servers.gateway.pin_allowlist"):
        sys.modules.pop(mod, None)

    from mcp_servers.gateway.gateway_mcp_server import build_gateway

    gateway = build_gateway(
        server_name="edms",
        upstream_url="http://127.0.0.1:65535",
    )
    assert gateway is not None
    with pytest.raises(ValueError, match="platform"):
        build_gateway(server_name="platform", upstream_url="http://127.0.0.1:8082")
    # SSRF gate (020): an off-allowlist upstream must fail closed at build time.
    with pytest.raises(ValueError, match="upstream"):
        build_gateway(server_name="edms", upstream_url="http://evil.example.com:8080")
