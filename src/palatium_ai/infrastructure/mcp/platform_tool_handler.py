# src/palatium_ai/infrastructure/mcp/platform_tool_handler.py

"""In-process handler for canonical ``platform`` MCP tools (070)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Protocol

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.knowledge.types import IngestDocumentCommand, SearchKnowledgeQuery
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.infrastructure.mcp.graph_web_tool_ops import graph_query, web_fallback
from palatium_ai.infrastructure.mcp.memory_tool_ops import (
    consolidate_memory,
    forget_memory,
    save_memory,
    search_memory,
)

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.domain.graph.port import GraphPort
    from palatium_ai.domain.knowledge.port import KnowledgePort
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.web.port import WebSearchPort


class LocalMcpToolHandler(Protocol):
    """Execute MCP tool calls in-process (bypass HTTP stub)."""

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> MCPToolResult: ...


class PlatformToolHandler:
    """Routes ``platform`` canonical tools to KnowledgePort / MemoryPort / GraphPort / WebSearchPort."""

    def __init__(
        self,
        *,
        knowledge_port: KnowledgePort,
        memory_port: MemoryPort | None = None,
        consolidation: MemoryConsolidationService | None = None,
        graph_port: GraphPort | None = None,
        web_search_port: WebSearchPort | None = None,
    ) -> None:
        self._knowledge = knowledge_port
        self._memory = memory_port
        self._consolidation = consolidation
        self._graph = graph_port
        self._web_search = web_search_port

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> MCPToolResult:
        if tool_name == "ingest_document":
            return await self._ingest_document(arguments)
        if tool_name == "search_knowledge":
            return await self._search_knowledge(arguments)
        if tool_name == "search_memory":
            return await self._search_memory(arguments)
        if tool_name == "save_memory":
            return await self._save_memory(arguments)
        if tool_name == "forget_memory":
            return await self._forget_memory(arguments)
        if tool_name == "consolidate_memory":
            return await consolidate_memory(self._consolidation, arguments)
        if tool_name == "graph_query":
            return await graph_query(self._graph, arguments)
        if tool_name == "web_fallback":
            return await web_fallback(self._web_search, arguments)
        msg = f"unsupported platform tool: {tool_name}"
        raise ValueError(msg)

    async def _search_memory(self, arguments: dict[str, object]) -> MCPToolResult:
        if self._memory is None:
            return _error_result("search_memory unavailable: memory port not configured")
        return await search_memory(self._memory, arguments)

    async def _save_memory(self, arguments: dict[str, object]) -> MCPToolResult:
        if self._memory is None:
            return _error_result("save_memory unavailable: memory port not configured")
        return await save_memory(self._memory, arguments)

    async def _forget_memory(self, arguments: dict[str, object]) -> MCPToolResult:
        if self._memory is None:
            return _error_result("forget_memory unavailable: memory port not configured")
        return await forget_memory(self._memory, arguments)

    async def _ingest_document(self, arguments: dict[str, object]) -> MCPToolResult:
        user_id = arguments.get("user_id")
        thread_id = arguments.get("thread_id")
        chunks_json = arguments.get("chunks_json")
        if not isinstance(user_id, str) or not user_id.strip():
            return _error_result("Invalid params: user_id is required")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return _error_result("Invalid params: thread_id is required")
        if not isinstance(chunks_json, str) or not chunks_json.strip():
            return _error_result("Invalid params: chunks_json is required")

        try:
            raw_chunks = json.loads(chunks_json)
        except json.JSONDecodeError:
            return _error_result("Invalid params: chunks_json must be valid JSON")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            return _error_result("Invalid params: chunks_json must be a non-empty array")

        chunks: list[TextChunk] = []
        for index, item in enumerate(raw_chunks):
            if not isinstance(item, dict):
                continue
            text_value = str(item.get("text", "")).strip()
            if not text_value:
                continue
            chunks.append(
                TextChunk(
                    index=int(item.get("index", index)),
                    text=text_value,
                    char_start=int(item.get("char_start", 0)),
                    char_end=int(item.get("char_end", len(text_value))),
                    contextual_prefix=str(item.get("contextual_prefix", ""))[:500],
                )
            )
        if not chunks:
            return _error_result("Invalid params: no valid chunks in payload")

        document_id = arguments.get("document_id")
        document_title = arguments.get("document_title")
        mime_type = arguments.get("mime_type")
        command = IngestDocumentCommand(
            user_id=user_id.strip(),
            thread_id=thread_id.strip(),
            document_id=(document_id.strip() if isinstance(document_id, str) and document_id.strip() else None),
            document_title=(
                document_title.strip() if isinstance(document_title, str) and document_title.strip() else None
            ),
            mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else None,
            chunks=tuple(chunks),
        )
        result = await self._knowledge.ingest_document(command)
        payload = {
            "tool": "ingest_document",
            "thread_id": result.thread_id,
            "document_ref": str(result.document_ref),
            "chunk_count": result.chunk_count,
            "status": result.status,
        }
        return MCPToolResult(
            content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            is_error=False,
        )

    async def _search_knowledge(self, arguments: dict[str, object]) -> MCPToolResult:
        user_id = arguments.get("user_id")
        query = arguments.get("query")
        if not isinstance(user_id, str) or not user_id.strip():
            return _error_result("Invalid params: user_id is required")
        if not isinstance(query, str) or not query.strip():
            return _error_result("Invalid params: query is required")

        thread_id_raw = arguments.get("thread_id", "")
        thread_id = thread_id_raw.strip() if isinstance(thread_id_raw, str) and thread_id_raw.strip() else None
        limit_raw = arguments.get("limit", "8")
        try:
            limit = max(1, min(int(str(limit_raw).strip()), 32))
        except ValueError:
            return _error_result("Invalid params: limit must be an integer between 1 and 32")

        result = await self._knowledge.search_knowledge(
            SearchKnowledgeQuery(
                user_id=user_id.strip(),
                query=query.strip(),
                thread_id=thread_id,
                limit=limit,
            )
        )
        payload = {
            "tool": "search_knowledge",
            "query": result.query,
            "hits": [
                {
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "chunk_index": hit.chunk_index,
                    "text": hit.text,
                    "contextual_prefix": hit.contextual_prefix,
                    "thread_id": hit.thread_id,
                    "document_title": hit.document_title,
                    "score": hit.score,
                }
                for hit in result.hits
            ],
            "hit_count": len(result.hits),
        }
        return MCPToolResult(
            content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            is_error=False,
        )


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )
