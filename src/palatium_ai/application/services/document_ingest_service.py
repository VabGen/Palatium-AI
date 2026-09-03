# src/palatium_ai/application/services/document_ingest_service.py

"""Подготовка текста и HITL-gated ingest через platform.ingest_document (off hot path)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.orchestration.agent_bridge import (
    text_ingestor_output_to_task_result,
    text_ingestor_to_agent_input,
)
from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.text_ingestor import TextIngestorInput, TextIngestorTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.ingest.commit import IngestCommitPayload
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.text_ingestor import TextIngestorAgent
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PENDING_PREFIX = "doc_ingest:pending:"
_PENDING_TTL_SECONDS = 30 * 60
_PLATFORM_SERVER = "platform"
_INGEST_TOOL = "ingest_document"
_DOC_INGEST_TASK_PREFIX = "doc-ingest-"


class DocumentIngestService:
    """Chunking/normalization facade; MCP write only after HITL approval (020)."""

    def __init__(
        self,
        *,
        harness: Harness,
        text_ingestor: TextIngestorAgent,
        hitl_service: HitlService,
        mcp_registry: MCPRegistryPort,
        redis_client: Redis | None = None,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
    ) -> None:
        self._harness = harness
        self._text_ingestor = text_ingestor
        self._hitl = hitl_service
        self._mcp_registry = mcp_registry
        self._redis = redis_client
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._memory_pending: dict[str, IngestCommitPayload] = {}

    @traceable(name="document_ingest.prepare_chunks")
    async def prepare_chunks(
        self,
        *,
        task_id: str,
        thread_id: str,
        raw_text: str,
        document_id: str | None = None,
        mime_type: str | None = None,
        locale: str | None = None,
        max_chunk_chars: int = 1500,
        enrich_context_prefix: bool = False,
        document_title: str | None = None,
        trace_id: str | None = None,
    ) -> TextIngestorTaskResult:
        task_input = TextIngestorInput(
            task_id=task_id,
            thread_id=thread_id,
            document_id=document_id,
            raw_text=raw_text,
            mime_type=mime_type,
            locale=locale,
            max_chunk_chars=max_chunk_chars,
            enrich_context_prefix=enrich_context_prefix,
            document_title=document_title,
        )
        agent_input = text_ingestor_to_agent_input(
            task_input,
            trace_id=trace_id or f"ingest-{task_id}",
            thread_id=thread_id,
        )
        agent_output = await self._harness.execute_with_guardrails(self._text_ingestor, agent_input)
        result = text_ingestor_output_to_task_result(
            agent_output,
            task_id=task_id,
            agent_role=self._text_ingestor.config.role,
        )
        if result.output is not None and result.status != "failure":
            await self._store_pending(
                IngestCommitPayload(
                    thread_id=thread_id,
                    prepare_task_id=task_id,
                    document_id=document_id,
                    document_title=document_title,
                    mime_type=mime_type,
                    chunks=result.output.chunks,
                )
            )
            logger.info(
                "document_ingest.prepared",
                task_id=task_id,
                thread_id=thread_id,
                chunk_count=len(result.output.chunks),
                strategy=result.output.chunking_strategy,
                context_prefixes_applied=result.output.context_prefixes_applied,
            )
        return result

    @traceable(name="document_ingest.request_commit")
    async def request_commit(
        self,
        *,
        prepare_task_id: str,
        owner_user_id: str,
        org_id: str | None,
    ) -> HITLCardView:
        """Create HITL card for platform.ingest_document; payload must exist from prepare."""
        payload = await self._load_pending(prepare_task_id)
        if payload is None:
            msg = f"prepared ingest not found for task_id={prepare_task_id}"
            raise ValueError(msg)
        if not payload.chunks:
            msg = "prepared ingest has no chunks"
            raise ValueError(msg)

        commit_task_id = f"{_DOC_INGEST_TASK_PREFIX}{uuid4().hex[:12]}"
        preview = (
            f"thread_id={payload.thread_id}; chunks={len(payload.chunks)}; document_id={payload.document_id or '(new)'}"
        )
        card = await self._hitl.create_tool_approval_card(
            thread_id=payload.thread_id,
            task_id=commit_task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_INGEST_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("high"),
            argument_preview=preview,
            owner_user_id=owner_user_id,
            org_id=org_id,
            ttl_seconds=5 * 60,
        )
        await self._delete_pending(prepare_task_id)
        await self._store_pending(
            payload.model_copy(update={"user_id": owner_user_id, "prepare_task_id": commit_task_id})
        )
        return card

    @traceable(name="document_ingest.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run platform.ingest_document after HITL approve (off-graph path)."""
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending ingest payload missing for task_id={task_id}"
            raise ValueError(msg)
        if not payload.user_id.strip():
            msg = "pending ingest missing user_id"
            raise ValueError(msg)
        chunks_payload = [
            {
                "index": chunk.index,
                "text": chunk.text,
                "contextual_prefix": chunk.contextual_prefix,
            }
            for chunk in payload.chunks
        ]
        arguments: dict[str, object] = {
            "user_id": payload.user_id,
            "thread_id": payload.thread_id,
            "chunks_json": json.dumps(chunks_payload, ensure_ascii=False),
        }
        if payload.document_id:
            arguments["document_id"] = payload.document_id
        if payload.document_title:
            arguments["document_title"] = payload.document_title
        if payload.mime_type:
            arguments["mime_type"] = payload.mime_type

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_INGEST_TOOL,
                arguments=arguments,
                actor_user_id=payload.user_id,
                actor_thread_id=payload.thread_id,
            ),
            self._mcp_registry,
            conversation_id=payload.thread_id,
            repository=self._mcp_tool_call_repository,
        )
        await self._delete_pending(task_id)
        await self._delete_pending(payload.prepare_task_id)
        if outcome.is_error:
            msg = "ingest_document MCP call failed"
            raise RuntimeError(msg)
        logger.info(
            "document_ingest.committed",
            thread_id=payload.thread_id,
            task_id=task_id,
            chunk_count=len(payload.chunks),
        )
        return {"content": outcome.content, "chunk_count": len(payload.chunks)}

    async def discard_pending(self, *, task_id: str) -> None:
        await self._delete_pending(task_id)

    async def _store_pending(self, payload: IngestCommitPayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.prepare_task_id}"
        raw = payload.model_dump_json()
        if self._redis is None:
            self._memory_pending[payload.prepare_task_id] = payload
            return
        await self._redis.set(key, raw, ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> IngestCommitPayload | None:
        if self._redis is None:
            return self._memory_pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._memory_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = IngestCommitPayload.model_validate_json(text)
        self._memory_pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._memory_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")
