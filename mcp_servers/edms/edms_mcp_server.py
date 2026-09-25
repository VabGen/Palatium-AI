# mcp_servers/edms/edms_mcp_server.py

"""EDMS MCP stub on FastMCP Streamable HTTP (real EDMS adapter later — 090)."""

from __future__ import annotations

from mcp_servers.mcp_stub_runtime import build_http_app, create_stub_mcp, register_pinned_tool
from palatium_ai.domain.mcp.external_schemas import (
    EDMS_ARCHIVE_DOCUMENT_SCHEMA,
    EDMS_DOCUMENT_ID_MAX_CHARS,
    EDMS_QUERY_MAX_CHARS,
    EDMS_SEARCH_DOCUMENTS_SCHEMA,
)

_MAX_HITS = 5
_MAX_QUERY_CHARS = EDMS_QUERY_MAX_CHARS
_MAX_DOCUMENT_ID_CHARS = EDMS_DOCUMENT_ID_MAX_CHARS

mcp = create_stub_mcp(
    name="edms",
    instructions=(
        "EDMS stub: search_documents (read) and archive_document (write/HITL). Not the production Канцлер NEXT adapter."
    ),
)


def search_documents(query: str) -> dict[str, object]:
    """Search EDMS documents by a free-text query."""
    q = query.strip()[:_MAX_QUERY_CHARS]
    if not q:
        raise ValueError("query is required")
    return {
        "stub": True,
        "tool": "search_documents",
        "query": q,
        "hits": [
            {
                "document_id": "stub-doc-1",
                "title": f"Match for: {q[:80]}",
                "score": 0.91,
            },
        ][:_MAX_HITS],
        "truncated": True,
        "max_hits": _MAX_HITS,
    }


def archive_document(document_id: str) -> dict[str, object]:
    """Archive one EDMS document by exact document_id (write stub)."""
    doc_id = document_id.strip()[:_MAX_DOCUMENT_ID_CHARS]
    if not doc_id:
        raise ValueError("document_id is required")
    if "*" in doc_id or "?" in doc_id:
        raise ValueError("document_id must be exact (no wildcards)")
    return {
        "stub": True,
        "tool": "archive_document",
        "document_id": doc_id,
        "status": "archived",
    }


register_pinned_tool(
    mcp,
    fn=search_documents,
    name="search_documents",
    description=(
        "Search EDMS documents by a free-text query. "
        "Use for lookup/read of contracts, incoming/outgoing, or archive titles. "
        "Do not use for archive/write. "
        f"Returns truncated stub hits: document_id, title, score (max {_MAX_HITS}). "
        "Never invent ids beyond returned hits."
    ),
    input_schema=EDMS_SEARCH_DOCUMENTS_SCHEMA,
    read_only=True,
)
register_pinned_tool(
    mcp,
    fn=archive_document,
    name="archive_document",
    description=(
        "Archive one EDMS document by exact document_id. "
        "Write operation: Host must require HITL before call. "
        "document_id must be exact (no wildcards)."
    ),
    input_schema=EDMS_ARCHIVE_DOCUMENT_SCHEMA,
    read_only=False,
)

app = build_http_app(mcp, server="edms")
