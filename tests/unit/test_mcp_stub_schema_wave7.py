# tests/unit/test_mcp_stub_schema_wave7.py

"""Wave 7: live MCP stub inputSchema must match platform pins (no spurious HITL)."""

from __future__ import annotations

import importlib.util
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
    PLATFORM_CONSOLIDATE_MEMORY_SCHEMA,
    PLATFORM_FORGET_MEMORY_SCHEMA,
    PLATFORM_GRAPH_QUERY_SCHEMA,
    PLATFORM_INGEST_DOCUMENT_SCHEMA,
    PLATFORM_SAVE_MEMORY_SCHEMA,
    PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
    PLATFORM_SEARCH_MEMORY_SCHEMA,
    PLATFORM_WEB_FALLBACK_SCHEMA,
)
from palatium_ai.domain.mcp.tool_policy import (
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
    schema_fingerprint,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_ROOT = _REPO_ROOT / "mcp_servers"


def _load_stub_contract(module_name: str, contract_path: Path) -> object:
    if str(_MCP_ROOT) not in sys.path:
        sys.path.insert(0, str(_MCP_ROOT))
    spec = importlib.util.spec_from_file_location(module_name, contract_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def edms_contract() -> object:
    return _load_stub_contract("edms_contract", _MCP_ROOT / "edms" / "contract.py")


@pytest.fixture(scope="module")
def analytics_contract() -> object:
    return _load_stub_contract("analytics_contract", _MCP_ROOT / "analytics" / "contract.py")


def test_platform_and_stub_search_schema_fingerprints_match(edms_contract: object) -> None:
    stub_schema = edms_contract.SEARCH_DOCUMENTS_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(EDMS_SEARCH_DOCUMENTS_SCHEMA)


def test_platform_and_stub_archive_schema_fingerprints_match(edms_contract: object) -> None:
    stub_schema = edms_contract.ARCHIVE_DOCUMENT_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(EDMS_ARCHIVE_DOCUMENT_SCHEMA)


def test_platform_and_stub_analytics_schema_fingerprints_match(analytics_contract: object) -> None:
    stub_schema = analytics_contract.SALES_METRICS_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(ANALYTICS_SALES_METRICS_SCHEMA)


@pytest.fixture(scope="module")
def platform_contract() -> object:
    return _load_stub_contract("platform_contract", _MCP_ROOT / "platform" / "contract.py")


def test_platform_and_stub_ingest_schema_fingerprints_match(platform_contract: object) -> None:
    stub_schema = platform_contract.INGEST_DOCUMENT_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(PLATFORM_INGEST_DOCUMENT_SCHEMA)


def test_platform_and_stub_search_knowledge_schema_fingerprints_match(platform_contract: object) -> None:
    stub_schema = platform_contract.SEARCH_KNOWLEDGE_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(PLATFORM_SEARCH_KNOWLEDGE_SCHEMA)


def test_platform_and_stub_search_memory_schema_fingerprints_match(platform_contract: object) -> None:
    stub_schema = platform_contract.SEARCH_MEMORY_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(PLATFORM_SEARCH_MEMORY_SCHEMA)


def test_platform_and_stub_graph_query_schema_fingerprints_match(platform_contract: object) -> None:
    stub_schema = platform_contract.GRAPH_QUERY_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(PLATFORM_GRAPH_QUERY_SCHEMA)


def test_platform_and_stub_web_fallback_schema_fingerprints_match(platform_contract: object) -> None:
    stub_schema = platform_contract.WEB_FALLBACK_INPUT_SCHEMA  # type: ignore[attr-defined]
    assert schema_fingerprint(stub_schema) == schema_fingerprint(PLATFORM_WEB_FALLBACK_SCHEMA)


@pytest.mark.parametrize(
    ("server_name", "tool_name", "input_schema", "expected_side_effect"),
    [
        ("edms", "search_documents", EDMS_SEARCH_DOCUMENTS_SCHEMA, "read"),
        ("edms", "archive_document", EDMS_ARCHIVE_DOCUMENT_SCHEMA, "write"),
        ("analytics", "get_sales_metrics", ANALYTICS_SALES_METRICS_SCHEMA, "read"),
        ("platform", "ingest_document", PLATFORM_INGEST_DOCUMENT_SCHEMA, "write"),
        ("platform", "search_knowledge", PLATFORM_SEARCH_KNOWLEDGE_SCHEMA, "read"),
        ("platform", "search_memory", PLATFORM_SEARCH_MEMORY_SCHEMA, "read"),
        ("platform", "save_memory", PLATFORM_SAVE_MEMORY_SCHEMA, "write"),
        ("platform", "forget_memory", PLATFORM_FORGET_MEMORY_SCHEMA, "write"),
        ("platform", "consolidate_memory", PLATFORM_CONSOLIDATE_MEMORY_SCHEMA, "write"),
        ("platform", "graph_query", PLATFORM_GRAPH_QUERY_SCHEMA, "read"),
        ("platform", "web_fallback", PLATFORM_WEB_FALLBACK_SCHEMA, "read"),
    ],
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


def test_search_documents_read_path_skips_hitl(edms_contract: object) -> None:
    descriptor = MCPToolDescriptor(
        name="search_documents",
        description="Search EDMS documents.",
        inputSchema=edms_contract.SEARCH_DOCUMENTS_INPUT_SCHEMA,  # type: ignore[attr-defined]
    )
    pin = resolve_platform_pin(descriptor, server_name="edms")
    assert pin is not None
    assert pin.requires_hitl is False
    assert requires_interrupt_before_call("read", pin=pin) is False


def test_archive_document_is_irreversible_write(edms_contract: object) -> None:
    descriptor = MCPToolDescriptor(
        name="archive_document",
        description="Archive EDMS document.",
        inputSchema=edms_contract.ARCHIVE_DOCUMENT_INPUT_SCHEMA,  # type: ignore[attr-defined]
    )
    pin = resolve_platform_pin(descriptor, server_name="edms")
    assert pin is not None
    assert pin.side_effect == "write"
    assert pin.irreversible is True
    assert pin.requires_hitl is True
