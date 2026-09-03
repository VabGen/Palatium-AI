# src/palatium_ai/infrastructure/mcp/memory_tool_ops.py

"""In-process MCP memory tool operations (070 thin wrappers over MemoryPort)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.core.security.secret_scanner import scan_text
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.pii import resolve_contains_pii
from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.domain.memory.ports import MemoryPort

_VALID_NAMESPACE_KINDS = frozenset({"thread", "user", "org"})
_VALID_MEMORY_TYPES: frozenset[str] = frozenset({"preference", "fact", "incident", "episode"})


def resolve_memory_namespace(*, kind: str, scope_id: str, user_id: str) -> tuple[str, ...]:
    """Map MCP namespace_kind + scope_id to MemoryPort namespace tuple."""
    normalized = kind.strip().lower()
    scope = scope_id.strip()
    if normalized == "thread":
        if not scope:
            msg = "scope_id (thread_id) is required for thread namespace"
            raise ValueError(msg)
        return thread_namespace(scope)
    if normalized == "user":
        return user_namespace(scope or user_id)
    if normalized == "org":
        return org_namespace(scope or "default")
    msg = f"unsupported namespace_kind: {kind}"
    raise ValueError(msg)


def parse_limit(raw: object, *, default: int = 8) -> int | None:
    try:
        return max(1, min(int(str(raw).strip()), 32))
    except TypeError, ValueError:
        return None


def _search_namespaces(
    *,
    user_id: str,
    thread_id: object,
    org_id: object,
) -> list[tuple[str, ...]]:
    namespaces: list[tuple[str, ...]] = []
    if isinstance(thread_id, str) and thread_id.strip():
        namespaces.append(thread_namespace(thread_id.strip()))
    namespaces.append(user_namespace(user_id))
    if isinstance(org_id, str) and org_id.strip():
        namespaces.append(org_namespace(org_id.strip()))
    return namespaces


async def _collect_memory_hits(
    memory_port: MemoryPort,
    *,
    namespaces: list[tuple[str, ...]],
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    seen: set[str] = set()
    for namespace in namespaces:
        for item in await memory_port.search(namespace=namespace, query=query, limit=limit):
            text = str(item.get("text", "")).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            hits.append(item)
            if len(hits) >= limit:
                return hits
    return hits


async def search_memory(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    user_id = arguments.get("user_id")
    query = arguments.get("query")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(query, str) or not query.strip():
        return _error_result("Invalid params: query is required")

    limit = parse_limit(arguments.get("limit", "8"))
    if limit is None:
        return _error_result("Invalid params: limit must be an integer between 1 and 32")

    namespaces = _search_namespaces(
        user_id=user_id.strip(),
        thread_id=arguments.get("thread_id", ""),
        org_id=arguments.get("org_id", ""),
    )
    hits = await _collect_memory_hits(
        memory_port,
        namespaces=namespaces,
        query=query.strip(),
        limit=limit,
    )
    payload = {
        "tool": "search_memory",
        "query": query.strip(),
        "hits": hits,
        "hit_count": len(hits),
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


def _parse_save_value(value_json: object) -> dict[str, object] | MCPToolResult:
    if not isinstance(value_json, str) or not value_json.strip():
        return _error_result("Invalid params: value_json is required")
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError:
        return _error_result("Invalid params: value_json must be valid JSON")
    if not isinstance(value, dict):
        return _error_result("Invalid params: value_json must be a JSON object")
    return value


def _validate_save_identity(
    arguments: dict[str, object],
) -> tuple[str, str, str, str] | MCPToolResult:
    user_id = arguments.get("user_id")
    namespace_kind = arguments.get("namespace_kind")
    scope_id = arguments.get("scope_id")
    entry_key = arguments.get("entry_key")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(namespace_kind, str) or namespace_kind.strip().lower() not in _VALID_NAMESPACE_KINDS:
        return _error_result("Invalid params: namespace_kind must be thread|user|org")
    if not isinstance(scope_id, str) or not scope_id.strip():
        return _error_result("Invalid params: scope_id is required")
    if not isinstance(entry_key, str) or not entry_key.strip():
        return _error_result("Invalid params: entry_key is required")
    return user_id.strip(), namespace_kind, scope_id.strip(), entry_key.strip()


def _check_save_scope(*, namespace_kind: str, scope_id: str, user_id: str, org_id: str) -> str | None:
    if not MemoryNamespacePolicy.mcp_user_scope_consistent(
        namespace_kind=namespace_kind,
        scope_id=scope_id,
        user_id=user_id,
    ):
        return "Invalid params: scope_id must equal user_id for user namespace"
    if not MemoryNamespacePolicy.mcp_org_scope_consistent(
        namespace_kind=namespace_kind,
        scope_id=scope_id,
        org_id=org_id,
    ):
        return "Invalid params: org_id must equal scope_id for org namespace"
    return None


async def save_memory(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    identity = _validate_save_identity(arguments)
    if isinstance(identity, MCPToolResult):
        return identity
    user_id, namespace_kind, scope_id, entry_key = identity

    value = _parse_save_value(arguments.get("value_json"))
    if isinstance(value, MCPToolResult):
        return value

    memory_type_raw = arguments.get("memory_type", "fact")
    memory_type = str(memory_type_raw).strip().lower() if memory_type_raw is not None else "fact"
    if memory_type not in _VALID_MEMORY_TYPES:
        return _error_result("Invalid params: memory_type must be preference|fact|incident|episode")

    text_value = str(value.get("text", "")).strip()
    if not text_value:
        return _error_result("Invalid params: value_json.text is required")
    scan_text(text_value, field="memory_entry")

    org_id_raw = arguments.get("org_id", "")
    org_id = org_id_raw.strip() if isinstance(org_id_raw, str) else ""
    scope_error = _check_save_scope(
        namespace_kind=str(namespace_kind),
        scope_id=scope_id,
        user_id=user_id,
        org_id=org_id,
    )
    if scope_error is not None:
        return _error_result(scope_error)

    client_pii = bool(value.get("contains_pii", False))
    pii_flag = resolve_contains_pii(text=text_value, client_flag=client_pii)

    stored = dict(value)
    stored.setdefault("user_id", user_id)
    stored["memory_type"] = memory_type
    stored["contains_pii"] = pii_flag

    try:
        namespace = resolve_memory_namespace(
            kind=namespace_kind,
            scope_id=scope_id,
            user_id=user_id,
        )
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    await memory_port.put(namespace=namespace, key=entry_key, value=stored)
    payload = {
        "tool": "save_memory",
        "namespace": "/".join(namespace),
        "entry_key": entry_key,
        "status": "saved",
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def forget_memory(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    user_id = arguments.get("user_id")
    namespace_kind = arguments.get("namespace_kind")
    scope_id = arguments.get("scope_id")
    entry_key = arguments.get("entry_key")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(namespace_kind, str) or namespace_kind.strip().lower() not in _VALID_NAMESPACE_KINDS:
        return _error_result("Invalid params: namespace_kind must be thread|user|org")
    if not isinstance(scope_id, str) or not scope_id.strip():
        return _error_result("Invalid params: scope_id is required")
    if not isinstance(entry_key, str) or not entry_key.strip():
        return _error_result("Invalid params: entry_key is required")

    if not MemoryNamespacePolicy.mcp_user_scope_consistent(
        namespace_kind=namespace_kind,
        scope_id=scope_id.strip(),
        user_id=user_id.strip(),
    ):
        return _error_result("Invalid params: scope_id must equal user_id for user namespace")

    org_id_raw = arguments.get("org_id", "")
    org_id = org_id_raw.strip() if isinstance(org_id_raw, str) else ""
    if not MemoryNamespacePolicy.mcp_org_scope_consistent(
        namespace_kind=namespace_kind,
        scope_id=scope_id.strip(),
        org_id=org_id,
    ):
        return _error_result("Invalid params: org_id must equal scope_id for org namespace")

    try:
        namespace = resolve_memory_namespace(
            kind=namespace_kind,
            scope_id=scope_id.strip(),
            user_id=user_id.strip(),
        )
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    forgotten = await memory_port.forget(namespace=namespace, key=entry_key.strip())
    payload = {
        "tool": "forget_memory",
        "namespace": "/".join(namespace),
        "entry_key": entry_key.strip(),
        "forgotten": forgotten,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def consolidate_memory(
    consolidation: MemoryConsolidationService | None,
    arguments: dict[str, object],
) -> MCPToolResult:
    user_id = arguments.get("user_id")
    thread_id = arguments.get("thread_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return _error_result("Invalid params: thread_id is required")
    if consolidation is None:
        return _error_result("consolidate_memory unavailable: consolidation worker not configured")

    task_id_raw = arguments.get("task_id", "")
    task_id = (
        task_id_raw.strip()
        if isinstance(task_id_raw, str) and task_id_raw.strip()
        else f"mcp-consolidate-{thread_id.strip()[:32]}"
    )
    org_id_raw = arguments.get("org_id", "")
    org_id = org_id_raw.strip() if isinstance(org_id_raw, str) and org_id_raw.strip() else None
    queued = consolidation.enqueue(
        thread_id=thread_id.strip(),
        task_id=task_id,
        user_id=user_id.strip(),
        org_id=org_id,
    )
    payload = {
        "tool": "consolidate_memory",
        "thread_id": thread_id.strip(),
        "task_id": task_id,
        "status": "queued" if queued else "queue_full",
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=_is_error_status(payload["status"]),
    )


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )


def _is_error_status(status: str) -> bool:
    return status == "queue_full"
