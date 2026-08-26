"""Unit tests for MCP registry URL allowlist / SSRF gate."""

from __future__ import annotations

import pytest

from palatium_ai.domain.mcp.server_url_policy import (
    UnsafeMcpServerUrlError,
    assert_mcp_server_url_safe,
    filter_mcp_server_map,
)


def test_https_public_host_allowed() -> None:
    assert assert_mcp_server_url_safe("https://edms.internal.example/mcp") == ("https://edms.internal.example/mcp")


def test_http_loopback_allowed() -> None:
    assert assert_mcp_server_url_safe("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert assert_mcp_server_url_safe("http://localhost:8080") == "http://localhost:8080"


def test_http_compose_dns_allowed_via_allowlist() -> None:
    assert (
        assert_mcp_server_url_safe(
            "http://mcp-edms:8080",
            http_allowed_hosts={"mcp-edms", "localhost"},
        )
        == "http://mcp-edms:8080"
    )


def test_http_arbitrary_host_denied() -> None:
    with pytest.raises(UnsafeMcpServerUrlError):
        assert_mcp_server_url_safe("http://evil.example.com/mcp")


def test_metadata_ip_denied() -> None:
    with pytest.raises(UnsafeMcpServerUrlError):
        assert_mcp_server_url_safe("http://169.254.169.254/latest/meta-data")
    with pytest.raises(UnsafeMcpServerUrlError):
        assert_mcp_server_url_safe("https://169.254.169.254/latest/meta-data")


def test_embedded_credentials_denied() -> None:
    with pytest.raises(UnsafeMcpServerUrlError):
        assert_mcp_server_url_safe("https://user:pass@edms.example/mcp")


def test_filter_skips_bad_entries() -> None:
    accepted, rejected = filter_mcp_server_map(
        {
            "edms": "http://127.0.0.1:8080",
            "evil": "http://169.254.169.254/",
        }
    )
    assert set(accepted) == {"edms"}
    assert rejected and rejected[0][0] == "evil"
