# mcp_servers/platform/platform_mcp_server.py

"""Platform MCP stub — optional external discovery/schema smoke only.

Track B: Host runtime does NOT use this process. Discovery = static pins on Host;
execute = PlatformToolHandler. Start only via ``dev-up.ps1 -WithPlatformStub``.
All tools/call raise PermissionError (no fake success).
"""

from __future__ import annotations

from mcp_servers.mcp_stub_runtime import build_http_app, create_stub_mcp, register_pinned_tool
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

_DISCOVERY_ONLY = (
    "platform MCP stub is discovery-only; Host must execute via in-process PlatformToolHandler (refusing fake success)"
)

mcp = create_stub_mcp(
    name="platform",
    instructions=(
        "Platform stub for tools/list + schema pins only. "
        "All tools/call responses are errors — production Host uses local PlatformToolHandler."
    ),
)


def _refuse_execution(**_kwargs: object) -> dict[str, object]:
    """Never acknowledge writes/reads on the HTTP stub (Phase 2 single execution path)."""
    raise PermissionError(_DISCOVERY_ONLY)


def ingest_document(
    user_id: str,
    thread_id: str,
    chunks_json: str,
    document_id: str = "",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        thread_id=thread_id,
        chunks_json=chunks_json,
        document_id=document_id,
    )


def search_knowledge(
    user_id: str,
    query: str,
    thread_id: str = "",
    limit: str = "8",
    project_id: str = "",
    document_id: str = "",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        query=query,
        thread_id=thread_id,
        limit=limit,
        project_id=project_id,
        document_id=document_id,
    )


def search_memory(
    user_id: str,
    query: str,
    thread_id: str = "",
    org_id: str = "",
    limit: str = "8",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        query=query,
        thread_id=thread_id,
        org_id=org_id,
        limit=limit,
    )


def save_memory(
    user_id: str,
    namespace_kind: str,
    scope_id: str,
    entry_key: str,
    value_json: str,
    memory_type: str = "fact",
    org_id: str = "",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        namespace_kind=namespace_kind,
        scope_id=scope_id,
        entry_key=entry_key,
        value_json=value_json,
        memory_type=memory_type,
        org_id=org_id,
    )


def forget_memory(
    user_id: str,
    namespace_kind: str,
    scope_id: str,
    entry_key: str,
    org_id: str = "",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        namespace_kind=namespace_kind,
        scope_id=scope_id,
        entry_key=entry_key,
        org_id=org_id,
    )


def extract_transcript_memories(
    user_id: str,
    thread_id: str,
    task_id: str = "",
    org_id: str = "",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        thread_id=thread_id,
        task_id=task_id,
        org_id=org_id,
    )


def graph_query(
    user_id: str,
    cypher: str,
    params_json: str = "{}",
    as_of: str = "",
    limit: str = "25",
) -> dict[str, object]:
    return _refuse_execution(
        user_id=user_id,
        cypher=cypher,
        params_json=params_json,
        as_of=as_of,
        limit=limit,
    )


def skill_reference(name: str) -> dict[str, object]:
    return _refuse_execution(name=name)


def web_fallback(user_id: str, query: str, max_results: str = "5") -> dict[str, object]:
    return _refuse_execution(user_id=user_id, query=query, max_results=max_results)


register_pinned_tool(
    mcp,
    fn=ingest_document,
    name="ingest_document",
    description=(
        "Persist prepared document chunks into the knowledge index (write). "
        "Platform HITL must approve before call. "
        "chunks_json is a JSON array of {index,text,contextual_prefix}. "
        "Returns {document_ref, chunk_count, status}."
    ),
    input_schema=PLATFORM_INGEST_DOCUMENT_SCHEMA,
    read_only=False,
)
register_pinned_tool(
    mcp,
    fn=search_knowledge,
    name="search_knowledge",
    description="Hybrid search over ingested knowledge chunks (read).",
    input_schema=PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
    read_only=True,
)
register_pinned_tool(
    mcp,
    fn=search_memory,
    name="search_memory",
    description="Hybrid search over episodic memory entries (read).",
    input_schema=PLATFORM_SEARCH_MEMORY_SCHEMA,
    read_only=True,
)
register_pinned_tool(
    mcp,
    fn=save_memory,
    name="save_memory",
    description="Upsert episodic memory entry (write; HITL required).",
    input_schema=PLATFORM_SAVE_MEMORY_SCHEMA,
    read_only=False,
)
register_pinned_tool(
    mcp,
    fn=forget_memory,
    name="forget_memory",
    description="Delete episodic memory entry by key (write; HITL required).",
    input_schema=PLATFORM_FORGET_MEMORY_SCHEMA,
    read_only=False,
    destructive=True,
)
register_pinned_tool(
    mcp,
    fn=extract_transcript_memories,
    name="extract_transcript_memories",
    description=(
        "Enqueue sleep-time extract (transcript → medium via MemoryKeeper; write; HITL)."
    ),
    input_schema=PLATFORM_EXTRACT_TRANSCRIPT_MEMORIES_SCHEMA,
    read_only=False,
)
register_pinned_tool(
    mcp,
    fn=graph_query,
    name="graph_query",
    description=(
        "Read-only parameterized Cypher against the knowledge graph "
        "($params only; bi-temporal MemoryFact via $as_of)."
    ),
    input_schema=PLATFORM_GRAPH_QUERY_SCHEMA,
    read_only=True,
)
register_pinned_tool(
    mcp,
    fn=skill_reference,
    name="skill_reference",
    description=(
        "Load procedural skill reference.md (or SKILL body) by catalog name (read)."
    ),
    input_schema=PLATFORM_SKILL_REFERENCE_SCHEMA,
    read_only=True,
)
register_pinned_tool(
    mcp,
    fn=web_fallback,
    name="web_fallback",
    description="External web search fallback after local knowledge/memory empty (source=web).",
    input_schema=PLATFORM_WEB_FALLBACK_SCHEMA,
    read_only=True,
)

app = build_http_app(mcp, server="platform")
