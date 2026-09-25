# tests/unit/test_mcp_jwt_auth.py

"""Phase 3: MCP JWT aud=mcp:<server> mint + resolve + stub MultiAuth policy."""

from __future__ import annotations

import sys
import time

from types import SimpleNamespace

import jwt
import pytest

from palatium_ai.core.config.mcp import MCPConfig
from palatium_ai.domain.mcp.auth_policy import mcp_audience
from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient
from palatium_ai.infrastructure.mcp.jwt_auth import issue_mcp_access_token, resolve_mcp_bearer


def test_mcp_audience_canonical() -> None:
    assert mcp_audience("edms") == "mcp:edms"
    assert mcp_audience(" platform ") == "mcp:platform"


def test_issue_mcp_access_token_binds_audience() -> None:
    secret = "phase3-test-secret-key-32chars!!"
    token = issue_mcp_access_token(server_name="edms", signing_secret=secret)
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="mcp:edms",
        issuer="palatium-mcp",
    )
    assert claims["sub"] == "palatium-host"
    assert claims["aud"] == "mcp:edms"
    assert claims["exp"] > int(time.time())


def test_mcp_config_empty_jwt_issuer_uses_default() -> None:
    mcp = MCPConfig.model_validate({"MCP_JWT_ISSUER": ""})
    assert mcp.jwt_issuer == "palatium-mcp"


def test_resolve_prefers_jwt_over_shared_static() -> None:
    mcp = MCPConfig.model_validate(
        {
            "MCP_AUTH_TOKEN": "legacy-static-token-value",
            "MCP_JWT_ISSUER": "palatium-mcp",
        }
    )
    token = resolve_mcp_bearer(
        mcp,
        "analytics",
        signing_secret="phase3-test-secret-key-32chars!!",
    )
    assert token is not None
    assert token != "legacy-static-token-value"
    claims = jwt.decode(
        token,
        "phase3-test-secret-key-32chars!!",
        algorithms=["HS256"],
        audience="mcp:analytics",
        issuer="palatium-mcp",
    )
    assert claims["aud"] == "mcp:analytics"


def test_resolve_per_server_static_override_beats_jwt() -> None:
    mcp = MCPConfig.model_validate(
        {
            "MCP_AUTH_TOKEN": "shared",
            "MCP_SERVER_AUTH_TOKENS": '{"edms":"override-edms-token"}',
        }
    )
    token = resolve_mcp_bearer(
        mcp,
        "edms",
        signing_secret="phase3-test-secret-key-32chars!!",
    )
    assert token == "override-edms-token"


def test_client_sends_jwt_bearer_when_settings_resolve() -> None:
    secret = "phase3-test-secret-key-32chars!!"

    # Resolution lives in infrastructure (`resolve_settings_bearer`, rule 000): the
    # settings stub exposes the signing secret, MCPConfig carries issuer/TTL/algorithm.
    mcp = MCPConfig(_env_file=None)  # type: ignore[call-arg]
    settings = SimpleNamespace(mcp=mcp, mcp_jwt_signing_secret=lambda: secret)
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        settings,  # type: ignore[arg-type]
        server_name="edms",
    )
    headers = client._auth_headers()
    assert "Authorization" in headers
    raw = headers["Authorization"].removeprefix("Bearer ").strip()
    claims = jwt.decode(
        raw,
        secret,
        algorithms=["HS256"],
        audience="mcp:edms",
        issuer="palatium-mcp",
    )
    assert claims["aud"] == "mcp:edms"


def test_stub_build_auth_accepts_jwt_and_static(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_JWT_SECRET", "phase3-test-secret-key-32chars!!")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "legacy-static")
    monkeypatch.setenv("MCP_JWT_ISSUER", "palatium-mcp")
    monkeypatch.delenv("MCP_ALLOW_ANON", raising=False)
    for mod in ("mcp_servers.mcp_stub_runtime", "mcp_servers.mcp_stub_auth"):
        sys.modules.pop(mod, None)
    from fastmcp.server.auth import MultiAuth

    from mcp_servers.mcp_stub_runtime import build_stub_auth

    auth = build_stub_auth(server_name="edms")
    assert isinstance(auth, MultiAuth)


def test_stub_build_auth_jwt_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_JWT_SECRET", "phase3-test-secret-key-32chars!!")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("MCP_ALLOW_ANON", raising=False)
    for mod in ("mcp_servers.mcp_stub_runtime", "mcp_servers.mcp_stub_auth"):
        sys.modules.pop(mod, None)
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    from mcp_servers.mcp_stub_runtime import build_stub_auth

    auth = build_stub_auth(server_name="platform")
    assert isinstance(auth, JWTVerifier)


def test_stub_build_auth_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_ALLOW_ANON", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    for mod in ("mcp_servers.mcp_stub_runtime", "mcp_servers.mcp_stub_auth"):
        sys.modules.pop(mod, None)
    from mcp_servers.mcp_stub_runtime import build_stub_auth

    with pytest.raises(RuntimeError, match="MCP_JWT_SECRET"):
        build_stub_auth(server_name="edms")


def test_stub_build_auth_denies_anon_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """020: the FastMCP auth path must also refuse an anonymous perimeter in staging/production."""
    monkeypatch.delenv("MCP_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ALLOW_ANON", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    for mod in ("mcp_servers.mcp_stub_runtime", "mcp_servers.mcp_stub_auth"):
        sys.modules.pop(mod, None)
    from mcp_servers.mcp_stub_runtime import build_stub_auth

    with pytest.raises(RuntimeError, match="MCP_ALLOW_ANON"):
        build_stub_auth(server_name="edms")
