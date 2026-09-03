# src/palatium_ai/domain/mcp/platform_schemas.py

"""Frozen pydantic I/O for canonical platform MCP tools (070)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from palatium_ai.domain.mcp.external_schemas import pinned_input_schema


class PlatformIngestDocumentInput(BaseModel):
    """Input for ``mcp:platform.ingest_document`` (write; HITL required)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(
        min_length=1,
        max_length=128,
        description="Owner user id for RLS-scoped knowledge writes.",
    )
    thread_id: str = Field(
        min_length=1,
        max_length=128,
        description="Conversation thread that owns the ingested document.",
    )
    document_id: str = Field(
        default="",
        max_length=128,
        description="Optional stable document identifier.",
    )
    chunks_json: str = Field(
        min_length=2,
        max_length=500_000,
        description="JSON array of {index,text,contextual_prefix} chunk payloads.",
    )


PLATFORM_INGEST_DOCUMENT_SCHEMA = pinned_input_schema(PlatformIngestDocumentInput)


class PlatformSearchKnowledgeInput(BaseModel):
    """Input for ``mcp:platform.search_knowledge`` (read)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(
        min_length=1,
        max_length=128,
        description="Owner user id for RLS-scoped knowledge reads.",
    )
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Natural-language search query over ingested knowledge chunks.",
    )
    thread_id: str = Field(
        default="",
        max_length=128,
        description="Optional thread scope; empty searches all user knowledge.",
    )
    limit: str = Field(
        default="8",
        max_length=2,
        description="Max hits to return (1-32), encoded as string for MCP schema.",
    )


PLATFORM_SEARCH_KNOWLEDGE_SCHEMA = pinned_input_schema(PlatformSearchKnowledgeInput)


class PlatformSearchMemoryInput(BaseModel):
    """Input for ``mcp:platform.search_memory`` (read)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128, description="Owner user id for RLS-scoped memory reads.")
    query: str = Field(min_length=1, max_length=500, description="Search query over episodic memory.")
    thread_id: str = Field(default="", max_length=128, description="Optional thread scope.")
    org_id: str = Field(default="", max_length=128, description="Optional org scope.")
    limit: str = Field(default="8", max_length=2, description="Max hits (1-32) as string.")


class PlatformSaveMemoryInput(BaseModel):
    """Input for ``mcp:platform.save_memory`` (write; HITL required)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16, description="thread|user|org")
    scope_id: str = Field(min_length=1, max_length=128, description="thread_id, user_id, or org_id")
    entry_key: str = Field(min_length=1, max_length=256)
    value_json: str = Field(min_length=2, max_length=50_000, description="JSON object with required text field.")
    memory_type: str = Field(default="fact", max_length=16, description="preference|fact|incident|episode")
    org_id: str = Field(
        default="",
        max_length=128,
        description="Required when namespace_kind=org; must equal scope_id.",
    )


class PlatformForgetMemoryInput(BaseModel):
    """Input for ``mcp:platform.forget_memory`` (write; HITL required)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    org_id: str = Field(
        default="",
        max_length=128,
        description="Required when namespace_kind=org; must equal scope_id.",
    )


class PlatformConsolidateMemoryInput(BaseModel):
    """Input for ``mcp:platform.consolidate_memory`` (write; HITL required)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(default="", max_length=128, description="Optional job id; auto-generated if empty.")
    org_id: str = Field(default="", max_length=128)


PLATFORM_SEARCH_MEMORY_SCHEMA = pinned_input_schema(PlatformSearchMemoryInput)
PLATFORM_SAVE_MEMORY_SCHEMA = pinned_input_schema(PlatformSaveMemoryInput)
PLATFORM_FORGET_MEMORY_SCHEMA = pinned_input_schema(PlatformForgetMemoryInput)
PLATFORM_CONSOLIDATE_MEMORY_SCHEMA = pinned_input_schema(PlatformConsolidateMemoryInput)


class PlatformGraphQueryInput(BaseModel):
    """Input for ``mcp:platform.graph_query`` (read-only parameterized Cypher)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128, description="Tenant user id injected as $user_id when absent.")
    cypher: str = Field(
        min_length=1,
        max_length=8_000,
        description="Read-only Cypher with $param placeholders (no string concat).",
    )
    params_json: str = Field(
        default="{}",
        max_length=50_000,
        description="JSON object of Cypher $params.",
    )
    limit: str = Field(default="25", max_length=3, description="Max rows (1-100) as string.")


class PlatformWebFallbackInput(BaseModel):
    """Input for ``mcp:platform.web_fallback`` (external read; last resort)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500, description="Web search query after local retrieval empty.")
    max_results: str = Field(default="5", max_length=2, description="Max hits (1-10) as string.")


PLATFORM_GRAPH_QUERY_SCHEMA = pinned_input_schema(PlatformGraphQueryInput)
PLATFORM_WEB_FALLBACK_SCHEMA = pinned_input_schema(PlatformWebFallbackInput)

__all__ = [
    "PLATFORM_CONSOLIDATE_MEMORY_SCHEMA",
    "PLATFORM_FORGET_MEMORY_SCHEMA",
    "PLATFORM_GRAPH_QUERY_SCHEMA",
    "PLATFORM_INGEST_DOCUMENT_SCHEMA",
    "PLATFORM_SAVE_MEMORY_SCHEMA",
    "PLATFORM_SEARCH_KNOWLEDGE_SCHEMA",
    "PLATFORM_SEARCH_MEMORY_SCHEMA",
    "PLATFORM_WEB_FALLBACK_SCHEMA",
    "PlatformConsolidateMemoryInput",
    "PlatformForgetMemoryInput",
    "PlatformGraphQueryInput",
    "PlatformIngestDocumentInput",
    "PlatformSaveMemoryInput",
    "PlatformSearchKnowledgeInput",
    "PlatformSearchMemoryInput",
    "PlatformWebFallbackInput",
]
