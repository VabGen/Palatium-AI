# tests/unit/test_mcp_stub_schema_wave7.py

"""Wave 7 / Phase 4: stub FastMCP tools use domain schema SoT (pin fingerprints)."""

from __future__ import annotations

import importlib
import sys

from pathlib import Path

import pytest

from palatium_ai.domain.mcp.external_schemas import (
    ANALYTICS_SALES_METRICS_SCHEMA,
    EDMS_ARCHIVE_DOCUMENT_SCHEMA,
    EDMS_SEARCH_DOCUMENTS_SCHEMA,
)
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.platform_schemas import (
    PLATFORM_EXTRACT_TRANSCRIPT_MEMORIES_SCHEMA,
    PLATFORM_FORGET_MEMORY_SCHEMA,
    PLATFORM_GRAPH_QUERY_SCHEMA,
    PLATFORM_INGEST_DOCUMENT_SCHEMA,
    PLATFORM_SAVE_MEMORY_SCHEMA,
    PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
    PLATFORM_SEARCH_MEMORY_SCHEMA,
    PLATFORM_SKILL_REFERENCE_SCHEMA,
    PLATFORM_WEB_FALLBACK_SCHEMA,
)
from palatium_ai.domain.mcp.tool_policy import (
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
    schema_fingerprint,
)

_MCP_ROOT = Path(__file__).resolve().parents[2] / "mcp_servers"


def _load_stub_server(module_path: str) -> object:
    """Import a stub server as a package module — the layout dev-up and the image use.

    No ``sys.path`` juggling: putting ``mcp_servers/`` (or ``mcp_servers/platform``) on
    the path shadows the stdlib ``platform`` module and breaks unrelated imports.
    """
    for mod in tuple(sys.modules):
        if mod == module_path or mod == "mcp_servers" or mod.startswith("mcp_servers."):
            sys.modules.pop(mod, None)
    # Stub auth is fail-closed (020): a token must exist while the module mints its
    # verifier. The value is never used here — only the registered tool schemas are read.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MCP_AUTH_TOKEN", "wave7-stub-schema-token")
        mp.delenv("MCP_JWT_SECRET", raising=False)
        mp.delenv("MCP_ALLOW_ANON", raising=False)
        return importlib.import_module(module_path)


@pytest.fixture(scope="module")
def edms_stub() -> object:
    return _load_stub_server("mcp_servers.edms.edms_mcp_server")


@pytest.fixture(scope="module")
def analytics_stub() -> object:
    return _load_stub_server("mcp_servers.analytics.analytics_mcp_server")


@pytest.fixture(scope="module")
def platform_stub() -> object:
    return _load_stub_server("mcp_servers.platform.platform_mcp_server")


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "stub_fixture, tool_name, domain_schema",
    (
        ("edms_stub", "search_documents", EDMS_SEARCH_DOCUMENTS_SCHEMA),
        ("edms_stub", "archive_document", EDMS_ARCHIVE_DOCUMENT_SCHEMA),
        ("analytics_stub", "get_sales_metrics", ANALYTICS_SALES_METRICS_SCHEMA),
        ("platform_stub", "ingest_document", PLATFORM_INGEST_DOCUMENT_SCHEMA),
        ("platform_stub", "search_knowledge", PLATFORM_SEARCH_KNOWLEDGE_SCHEMA),
        ("platform_stub", "search_memory", PLATFORM_SEARCH_MEMORY_SCHEMA),
        ("platform_stub", "save_memory", PLATFORM_SAVE_MEMORY_SCHEMA),
        ("platform_stub", "forget_memory", PLATFORM_FORGET_MEMORY_SCHEMA),
        ("platform_stub", "extract_transcript_memories", PLATFORM_EXTRACT_TRANSCRIPT_MEMORIES_SCHEMA),
        ("platform_stub", "graph_query", PLATFORM_GRAPH_QUERY_SCHEMA),
        ("platform_stub", "skill_reference", PLATFORM_SKILL_REFERENCE_SCHEMA),
        ("platform_stub", "web_fallback", PLATFORM_WEB_FALLBACK_SCHEMA),
    ),
)
async def test_stub_registered_schema_matches_domain_pin(
    stub_fixture: str,
    tool_name: str,
    domain_schema: dict[str, object],
    request: pytest.FixtureRequest,
) -> None:
    stub = request.getfixturevalue(stub_fixture)
    tool = await stub.mcp.get_tool(tool_name)  # type: ignore[attr-defined]
    registered = dict(tool.parameters)
    assert schema_fingerprint(registered) == schema_fingerprint(domain_schema)
    assert registered == domain_schema


@pytest.mark.parametrize(
    "server_name, tool_name, input_schema, expected_side_effect",
    (
        ("edms", "search_documents", EDMS_SEARCH_DOCUMENTS_SCHEMA, "read"),
        ("edms", "archive_document", EDMS_ARCHIVE_DOCUMENT_SCHEMA, "write"),
        ("analytics", "get_sales_metrics", ANALYTICS_SALES_METRICS_SCHEMA, "read"),
        ("platform", "ingest_document", PLATFORM_INGEST_DOCUMENT_SCHEMA, "write"),
        ("platform", "search_knowledge", PLATFORM_SEARCH_KNOWLEDGE_SCHEMA, "read"),
        ("platform", "search_memory", PLATFORM_SEARCH_MEMORY_SCHEMA, "read"),
        ("platform", "save_memory", PLATFORM_SAVE_MEMORY_SCHEMA, "write"),
        ("platform", "forget_memory", PLATFORM_FORGET_MEMORY_SCHEMA, "write"),
        ("platform", "extract_transcript_memories", PLATFORM_EXTRACT_TRANSCRIPT_MEMORIES_SCHEMA, "write"),
        ("platform", "graph_query", PLATFORM_GRAPH_QUERY_SCHEMA, "read"),
        ("platform", "skill_reference", PLATFORM_SKILL_REFERENCE_SCHEMA, "read"),
        ("platform", "web_fallback", PLATFORM_WEB_FALLBACK_SCHEMA, "read"),
    ),
)
def test_stub_schemas_resolve_platform_pins(
    server_name: str,
    tool_name: str,
    input_schema: dict[str, object],
    expected_side_effect: str,
) -> None:
    descriptor = MCPToolDescriptor(
        name=tool_name,
        description=f"stub {tool_name}",
        inputSchema=input_schema,
    )
    pin = resolve_platform_pin(descriptor, server_name=server_name)
    assert pin is not None, f"schema drift for mcp:{server_name}.{tool_name}"
    assert pin.side_effect == expected_side_effect
    assert classify_side_effect(descriptor, server_name=server_name) == expected_side_effect


def test_search_documents_read_path_skips_hitl() -> None:
    descriptor = MCPToolDescriptor(
        name="search_documents",
        description="Search EDMS documents.",
        inputSchema=EDMS_SEARCH_DOCUMENTS_SCHEMA,
    )
    pin = resolve_platform_pin(descriptor, server_name="edms")
    assert pin is not None
    assert pin.requires_hitl is False
    assert requires_interrupt_before_call("read", pin=pin) is False


def test_archive_document_is_irreversible_write() -> None:
    descriptor = MCPToolDescriptor(
        name="archive_document",
        description="Archive EDMS document.",
        inputSchema=EDMS_ARCHIVE_DOCUMENT_SCHEMA,
    )
    pin = resolve_platform_pin(descriptor, server_name="edms")
    assert pin is not None
    assert pin.side_effect == "write"
    assert pin.irreversible is True
    assert pin.requires_hitl is True


def test_drill_no_mirrored_stub_contracts() -> None:
    """Phase 4: contract.py / schema_util mirrors must stay deleted."""
    assert not (_MCP_ROOT / "schema_util.py").exists()
    for name in ("edms", "analytics", "platform"):
        assert not (_MCP_ROOT / name / "contract.py").exists(), name
