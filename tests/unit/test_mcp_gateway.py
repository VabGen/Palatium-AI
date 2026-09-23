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
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pin_allowlist() -> object:
    return _load("gateway_pin_allowlist", _GATEWAY / "pin_allowlist.py")


@pytest.fixture(scope="module")
def pin_filter() -> object:
    # pin_filter imports fastmcp — ensure allowlist path not required
    if str(_REPO / "mcp_servers") not in sys.path:
        sys.path.insert(0, str(_REPO / "mcp_servers"))
    if str(_GATEWAY) not in sys.path:
        sys.path.insert(0, str(_GATEWAY))
    return _load("gateway_pin_filter", _GATEWAY / "pin_filter.py")


def test_gateway_allowlist_matches_host_pins(pin_allowlist: object) -> None:
    catalog = pin_allowlist.GATEWAY_PINNED_TOOLS  # type: ignore[attr-defined]
    assert set(catalog) == {"edms", "analytics"}
    assert "platform" not in catalog
    for server, tools in catalog.items():
        assert frozenset(tools) == pinned_tool_names(server)


def test_gateway_rejects_platform_server(pin_allowlist: object) -> None:
    with pytest.raises(ValueError, match="platform"):
        pin_allowlist.allowlist_for("platform")  # type: ignore[attr-defined]


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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

    if str(_REPO / "mcp_servers") not in sys.path:
        sys.path.insert(0, str(_REPO / "mcp_servers"))
    if str(_GATEWAY) not in sys.path:
        sys.path.insert(0, str(_GATEWAY))

    for mod in ("gateway_mcp_server", "pin_allowlist", "pin_filter"):
        sys.modules.pop(mod, None)

    from gateway_mcp_server import build_gateway  # type: ignore[import-not-found]

    gateway = build_gateway(
        server_name="edms",
        upstream_url="http://127.0.0.1:65535",
    )
    assert gateway is not None
    with pytest.raises(ValueError, match="platform"):
        build_gateway(server_name="platform", upstream_url="http://127.0.0.1:8082")
