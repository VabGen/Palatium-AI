# mcp_servers/platform/contract.py

"""Frozen pydantic I/O for platform MCP stub — mirrors domain platform_schemas."""

from __future__ import annotations

import sys

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

try:
    from schema_util import pinned_input_schema
except ImportError:
    _mcp_root = Path(__file__).resolve().parent.parent
    if str(_mcp_root) not in sys.path:
        sys.path.insert(0, str(_mcp_root))
    from schema_util import pinned_input_schema

_MAX_THREAD_ID_CHARS = 128
_MAX_DOCUMENT_ID_CHARS = 128
_MAX_CHUNKS_JSON_CHARS = 500_000


class IngestDocumentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(
        min_length=1,
        max_length=128,
        description="Owner user id for RLS-scoped knowledge writes.",
    )
    thread_id: str = Field(
        min_length=1,
        max_length=_MAX_THREAD_ID_CHARS,
        description="Conversation thread that owns the ingested document.",
    )
    document_id: str = Field(
        default="",
        max_length=_MAX_DOCUMENT_ID_CHARS,
        description="Optional stable document identifier.",
    )
    chunks_json: str = Field(
        min_length=2,
        max_length=_MAX_CHUNKS_JSON_CHARS,
        description="JSON array of {index,text,contextual_prefix} chunk payloads.",
    )


INGEST_DOCUMENT_INPUT_SCHEMA = pinned_input_schema(IngestDocumentInput)


class SearchKnowledgeInput(BaseModel):
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
        max_length=_MAX_THREAD_ID_CHARS,
        description="Optional thread scope; empty searches all user knowledge.",
    )
    limit: str = Field(
        default="8",
        max_length=2,
        description="Max hits to return (1-32), encoded as string for MCP schema.",
    )


SEARCH_KNOWLEDGE_INPUT_SCHEMA = pinned_input_schema(SearchKnowledgeInput)


class SearchMemoryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    thread_id: str = Field(default="", max_length=_MAX_THREAD_ID_CHARS)
    org_id: str = Field(default="", max_length=128)
    limit: str = Field(default="8", max_length=2)


class SaveMemoryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    value_json: str = Field(min_length=2, max_length=50_000)
    memory_type: str = Field(default="fact", max_length=16)
    org_id: str = Field(default="", max_length=128)


class ForgetMemoryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    org_id: str = Field(default="", max_length=128)


class ConsolidateMemoryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=_MAX_THREAD_ID_CHARS)
    task_id: str = Field(default="", max_length=128)
    org_id: str = Field(default="", max_length=128)


SEARCH_MEMORY_INPUT_SCHEMA = pinned_input_schema(SearchMemoryInput)
SAVE_MEMORY_INPUT_SCHEMA = pinned_input_schema(SaveMemoryInput)
FORGET_MEMORY_INPUT_SCHEMA = pinned_input_schema(ForgetMemoryInput)
CONSOLIDATE_MEMORY_INPUT_SCHEMA = pinned_input_schema(ConsolidateMemoryInput)


class GraphQueryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    cypher: str = Field(min_length=1, max_length=8_000)
    params_json: str = Field(default="{}", max_length=50_000)
    limit: str = Field(default="25", max_length=3)


class WebFallbackInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    max_results: str = Field(default="5", max_length=2)


GRAPH_QUERY_INPUT_SCHEMA = pinned_input_schema(GraphQueryInput)
WEB_FALLBACK_INPUT_SCHEMA = pinned_input_schema(WebFallbackInput)
