# src/palatium_ai/application/services/memory_fact_persistence.py

"""Persist MemoryKeeper facts through platform ``save_memory`` MCP (060/070)."""

from __future__ import annotations

import hashlib
import json
import re

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.services.memory_consolidation import ConsolidationJob
from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.domain.agents.memory_keeper import MemoryFactCandidate
from palatium_ai.domain.memory.pii import resolve_contains_pii
from palatium_ai.domain.memory.types import MemoryType
from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PLATFORM_SERVER = "platform"
_SAVE_MEMORY_TOOL = "save_memory"
_CANONICAL_MEMORY_TYPES: frozenset[str] = frozenset({"preference", "fact", "incident", "episode"})


class MemoryFactPersistenceService:
    """Write sleep-time memory facts via MCP (audit + RBAC), not direct MemoryPort.put."""

    def __init__(
        self,
        mcp_registry: MCPRegistryPort,
        *,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
    ) -> None:
        self._mcp_registry = mcp_registry
        self._mcp_tool_call_repository = mcp_tool_call_repository

    async def persist_facts(
        self,
        *,
        job: ConsolidationJob,
        facts: tuple[MemoryFactCandidate, ...],
    ) -> int:
        """Persist ADD-only facts; returns count of successful MCP saves."""
        stored = 0
        for fact in facts:
            entry_key = _memory_key(fact.key_hint, fact.text)
            if await self._persist_one(job=job, fact=fact, entry_key=entry_key):
                stored += 1
        return stored

    async def _persist_one(
        self,
        *,
        job: ConsolidationJob,
        fact: MemoryFactCandidate,
        entry_key: str,
    ) -> bool:
        text_value = fact.text.strip()
        if not text_value:
            return False
        try:
            scan_text(text_value, field="memory_keeper_fact")
        except SecretScanError:
            logger.warning(
                "memory_fact_persistence.secret_blocked",
                thread_id=job.thread_id,
                task_id=job.task_id,
                entry_key=entry_key,
            )
            return False

        namespace_kind, scope_id = _resolve_fact_scope(fact=fact, job=job)
        user_id = _resolve_save_user_id(job=job, namespace_kind=namespace_kind, scope_id=scope_id)
        if not MemoryNamespacePolicy.mcp_user_scope_consistent(
            namespace_kind=namespace_kind,
            scope_id=scope_id,
            user_id=user_id,
        ):
            logger.warning(
                "memory_fact_persistence.scope_mismatch",
                thread_id=job.thread_id,
                task_id=job.task_id,
                namespace_kind=namespace_kind,
                scope_id=scope_id,
            )
            return False

        memory_type = _canonical_memory_type(fact.kind)
        pii_flag = resolve_contains_pii(text=text_value, client_flag=False)
        value = {
            "text": text_value,
            "kind": fact.kind,
            "confidence": fact.confidence,
            "source_task_id": job.task_id,
            "thread_id": job.thread_id,
            "user_id": job.user_id,
            "org_id": job.org_id,
            "contains_pii": pii_flag,
        }
        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_SAVE_MEMORY_TOOL,
                arguments={
                    "user_id": user_id,
                    "namespace_kind": namespace_kind,
                    "scope_id": scope_id,
                    "entry_key": entry_key,
                    "value_json": json.dumps(value, ensure_ascii=False),
                    "memory_type": memory_type,
                    "org_id": (job.org_id or "").strip() if namespace_kind == "org" else "",
                },
                actor_user_id=(job.user_id or "").strip(),
                actor_org_id=(job.org_id or "").strip(),
                actor_thread_id=job.thread_id.strip(),
            ),
            self._mcp_registry,
            conversation_id=job.thread_id,
            repository=self._mcp_tool_call_repository,
        )
        if outcome.is_error:
            logger.warning(
                "memory_fact_persistence.save_failed",
                thread_id=job.thread_id,
                task_id=job.task_id,
                entry_key=entry_key,
            )
            return False
        return True


def _resolve_fact_scope(*, fact: MemoryFactCandidate, job: ConsolidationJob) -> tuple[str, str]:
    """Map fact kind to MCP namespace_kind + scope_id (same routing as consolidation worker)."""
    if job.user_id and fact.kind == "preference":
        return "user", job.user_id.strip()
    if job.org_id and fact.kind == "entity":
        return "org", job.org_id.strip()
    return "thread", job.thread_id.strip()


def _resolve_save_user_id(*, job: ConsolidationJob, namespace_kind: str, scope_id: str) -> str:
    """Actor id for MCP; user namespace must equal scope_id (MEM-HITL-04)."""
    if namespace_kind == "user":
        return scope_id.strip()
    if job.user_id and job.user_id.strip():
        return job.user_id.strip()
    if namespace_kind == "org":
        return f"org:{scope_id}"
    return f"thread:{scope_id}"


def _canonical_memory_type(kind: str) -> MemoryType:
    normalized = kind.strip().lower()
    if normalized in _CANONICAL_MEMORY_TYPES:
        return normalized  # type: ignore[return-value]
    return "fact"


def _memory_key(key_hint: str | None, text: str) -> str:
    if key_hint:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", key_hint.strip().lower()).strip("-")[:80]
        if slug:
            return f"add:{slug}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"add:{digest}:{uuid4().hex[:8]}"
