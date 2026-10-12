# src/palatium_ai/infrastructure/mcp/platform_tool_handler.py

"""In-process handler for canonical ``platform`` MCP tools (070)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.attachments.errors import (
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentTooLargeError,
)
from palatium_ai.domain.attachments.read import AttachmentReadRequest
from palatium_ai.domain.knowledge.types import IngestDocumentCommand, SearchKnowledgeQuery
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.infrastructure.mcp.graph_web_tool_ops import graph_query, web_fallback
from palatium_ai.infrastructure.mcp.memory_tool_ops import (
    extract_transcript_memories,
    forget_memory,
    save_memory,
    search_memory,
)
from palatium_ai.infrastructure.mcp.skill_tool_ops import skill_reference

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_extract import MemoryExtractService
    from palatium_ai.domain.graph.port import GraphPort
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.knowledge.port import KnowledgePort
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.ports.attachment_read import AttachmentReadPort
    from palatium_ai.domain.skills.port import SkillCatalogPort
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
        consolidation: MemoryExtractService | None = None,
        graph_port: GraphPort | None = None,
        graph_write: GraphWritePort | None = None,
        web_search_port: WebSearchPort | None = None,
        skill_catalog: SkillCatalogPort | None = None,
        attachment_read: AttachmentReadPort | None = None,
    ) -> None:
        self._knowledge = knowledge_port
        self._memory = memory_port
        self._consolidation = consolidation
        self._graph = graph_port
        self._graph_write = graph_write
        self._web_search = web_search_port
        self._skills = skill_catalog
        self._attachment_read = attachment_read

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> MCPToolResult:
        handlers = {
            "ingest_document": self._ingest_document,
            "search_knowledge": self._search_knowledge,
            "search_memory": self._search_memory,
            "save_memory": self._save_memory,
            "forget_memory": self._forget_memory,
            "extract_transcript_memories": self._extract_transcript_memories,
            "graph_query": self._graph_query,
            "skill_reference": self._skill_reference,
            "web_fallback": self._web_fallback,
            "read_attachment": self._read_attachment,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            msg = f"unsupported platform tool: {tool_name}"
            raise ValueError(msg)
        return await handler(arguments)

    async def _extract_transcript_memories(self, arguments: dict[str, object]) -> MCPToolResult:
        return await extract_transcript_memories(self._consolidation, arguments)

    async def _graph_query(self, arguments: dict[str, object]) -> MCPToolResult:
        return await graph_query(self._graph, arguments)

    async def _skill_reference(self, arguments: dict[str, object]) -> MCPToolResult:
        return await skill_reference(self._skills, arguments)

    async def _web_fallback(self, arguments: dict[str, object]) -> MCPToolResult:
        return await web_fallback(self._web_search, arguments)

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
        return await forget_memory(self._memory, arguments, graph_write=self._graph_write)

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
            document_title=(document_title.strip() if isinstance(document_title, str) and document_title.strip() else None),
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
        project_raw = arguments.get("project_id", "")
        project_id = project_raw.strip() if isinstance(project_raw, str) and project_raw.strip() else None
        document_raw = arguments.get("document_id", "")
        source_document_id = document_raw.strip() if isinstance(document_raw, str) and document_raw.strip() else None
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
                project_id=project_id,
                source_document_id=source_document_id,
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

    async def _read_attachment(self, arguments: dict[str, object]) -> MCPToolResult:
        if self._attachment_read is None:
            return _error_result("read_attachment unavailable: attachment read port not configured")
        user_id = arguments.get("user_id")
        attachment_id_raw = arguments.get("attachment_id")
        if not isinstance(user_id, str) or not user_id.strip():
            return _error_result("Invalid params: user_id is required")
        if not isinstance(attachment_id_raw, str) or not attachment_id_raw.strip():
            return _error_result("Invalid params: attachment_id is required")
        try:
            attachment_id = UUID(attachment_id_raw.strip())
        except ValueError:
            return _error_result("Invalid params: attachment_id must be a UUID")

        max_chars = _parse_int_arg(arguments.get("max_chars", "32000"), default=32_000, lo=1, hi=500_000)
        if max_chars is None:
            return _error_result("Invalid params: max_chars must be an integer between 1 and 500000")
        offset = _parse_int_arg(arguments.get("offset", "0"), default=0, lo=0, hi=50_000_000)
        if offset is None:
            return _error_result("Invalid params: offset must be a non-negative integer")
        force_ocr = _parse_bool_arg(arguments.get("force_ocr", "false"))

        try:
            result = await self._attachment_read.read(
                AttachmentReadRequest(
                    attachment_id=attachment_id,
                    user_id=user_id.strip(),
                    max_chars=max_chars,
                    offset=offset,
                    force_ocr=force_ocr,
                )
            )
        except AttachmentNotFoundError:
            return _error_result("attachment not found")
        except AttachmentNotUsableError as exc:
            return _error_result(f"attachment not usable (state={exc.state})")
        except AttachmentTooLargeError as exc:
            return _error_result(
                f"attachment exceeds read ceiling ({exc.size_bytes}>{exc.max_size_bytes})",
            )

        body = result.notice if (result.notice and not result.text) else result.text
        fenced = f"<<<ATTACHMENT:{result.filename}>>>\n{body}\n<<<END_ATTACHMENT>>>"
        payload = {
            "tool": "read_attachment",
            "attachment_id": str(result.attachment_id),
            "filename": result.filename,
            "mime_type": result.mime_type,
            "truncated": result.truncated,
            "offset": result.offset,
            "total_chars": result.total_chars,
            "ocr_applied": result.ocr_applied,
            "ocr_cached": result.ocr_cached,
            "ocr_engine": result.ocr_engine,
            "extract_status": result.extract_status,
            "notice": result.notice,
            "fenced_text": fenced,
        }
        return MCPToolResult(
            content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            is_error=False,
        )


def _parse_int_arg(raw: object, *, default: int, lo: int, hi: int) -> int | None:
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value < lo or value > hi:
        return None
    return value


def _parse_bool_arg(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )
