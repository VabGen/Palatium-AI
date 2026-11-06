# src/palatium_ai/infrastructure/mcp/memory_tool_ops.py

"""In-process MCP memory tool operations (070 thin wrappers over MemoryPort)."""

from __future__ import annotations

import json

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from palatium_ai.core.logging import get_logger
from palatium_ai.core.security.secret_scanner import scan_text
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.domain.memory.emotional import parse_optional_emotional_valence
from palatium_ai.domain.memory.extract_queue import is_queued
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.pii import resolve_contains_pii
from palatium_ai.domain.memory.types import (
    MEMORY_EXPLICIT_WRITE_KEY,
    MEMORY_ORIGIN_KEY,
    MEMORY_TRUST_KEY,
    coerce_memory_origin,
    coerce_memory_trust,
    memory_trust_score,
    resolve_memory_origin,
    resolve_memory_trust,
)
from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_extract import MemoryExtractService
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

_VALID_NAMESPACE_KINDS = frozenset({"thread", "user", "org"})
_VALID_MEMORY_TYPES: frozenset[str] = frozenset({"preference", "fact", "incident", "episode"})
_VALID_VERIFY_VERDICTS: frozenset[str] = frozenset({"confirmed", "rejected"})
_VALID_AUDIT_TRUST_FILTERS: frozenset[str] = frozenset({"low", "inferred", "quarantined", "all"})
_VALID_AUDIT_ORIGINS: frozenset[str] = frozenset({"user_hitl", "extract", "compact", "system", "legacy"})


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

    try:
        valence = parse_optional_emotional_valence(value.get("emotional_valence"))
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    stored = dict(value)
    stored.setdefault("user_id", user_id)
    # HITL/MCP write: default trust so Select gate (recall min_confidence) is not
    # silently empty when callers omit confidence/importance (Memory OS Write).
    stored.setdefault("confidence", 1.0)
    stored.setdefault("importance", coerce_float(stored.get("confidence", 1.0)))
    stored["memory_type"] = memory_type
    stored["contains_pii"] = pii_flag
    _stamp_origin_trust(stored)
    if valence is not None:
        stored["emotional_valence"] = valence
    else:
        stored.pop("emotional_valence", None)

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
    *,
    graph_write: GraphWritePort | None = None,
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
    graph_expired = False
    if forgotten and graph_write is not None:
        # Fan-out: medium forget must not leave live long-term MemoryFact (060 / M5).
        try:
            graph_expired = await graph_write.expire_fact(
                user_id=user_id.strip(),
                entry_key=entry_key.strip(),
            )
        except Exception as exc:  # noqa: BLE001  # graph expiry is best-effort; the medium forget is recorded (060)
            logger.warning(
                "forget_memory.graph_expire_failed",
                entry_key=entry_key.strip()[:128],
                error=str(exc),
            )
            graph_expired = False
    payload = {
        "tool": "forget_memory",
        "namespace": "/".join(namespace),
        "entry_key": entry_key.strip(),
        "forgotten": forgotten,
        "graph_expired": graph_expired,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def extract_transcript_memories(
    consolidation: MemoryExtractService | None,
    arguments: dict[str, object],
) -> MCPToolResult:
    """Enqueue sleep-time extract (transcript → medium). Not graph promote."""
    user_id = arguments.get("user_id")
    thread_id = arguments.get("thread_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return _error_result("Invalid params: thread_id is required")
    if consolidation is None:
        return _error_result("extract_transcript_memories unavailable: extract worker not configured")

    task_id_raw = arguments.get("task_id", "")
    task_id = (
        task_id_raw.strip() if isinstance(task_id_raw, str) and task_id_raw.strip() else f"mcp-extract-{thread_id.strip()[:32]}"
    )
    org_id_raw = arguments.get("org_id", "")
    org_id = org_id_raw.strip() if isinstance(org_id_raw, str) and org_id_raw.strip() else None
    result = await consolidation.enqueue(
        thread_id=thread_id.strip(),
        task_id=task_id,
        user_id=user_id.strip(),
        org_id=org_id,
    )
    payload = {
        "tool": "extract_transcript_memories",
        "axis": "extract",
        "thread_id": thread_id.strip(),
        "task_id": task_id,
        "status": result,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=not is_queued(result),
    )


async def explain_belief(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    """Return provenance for one memory entry (ADR 0008 origin/trust + source link)."""
    identity = _validate_save_identity(arguments)
    if isinstance(identity, MCPToolResult):
        return identity
    user_id, namespace_kind, scope_id, entry_key = identity

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

    try:
        namespace = resolve_memory_namespace(
            kind=namespace_kind,
            scope_id=scope_id,
            user_id=user_id,
        )
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    item = await memory_port.get(namespace=namespace, key=entry_key)
    if item is None:
        return _error_result(f"memory entry not found: {entry_key}")

    origin = resolve_memory_origin(item)
    trust = resolve_memory_trust(item)
    created_at = str(item.get("_created_at") or item.get("created_at") or "").strip()
    source_task_id = str(item.get("source_task_id") or "").strip()
    source_thread_id = str(item.get("thread_id") or "").strip()
    payload = {
        "tool": "explain_belief",
        "namespace": "/".join(namespace),
        "entry_key": entry_key,
        "text": str(item.get("text", "")).strip(),
        "origin": origin,
        "trust": trust,
        "trust_score": memory_trust_score(trust),
        "created_at": created_at or None,
        "source": {
            "task_id": source_task_id or None,
            "thread_id": source_thread_id or None,
            "explicit_write": bool(item.get(MEMORY_EXPLICIT_WRITE_KEY)),
        },
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def memory_audit(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    """Owner-scoped listing of low-trust / filtered memory entries (CMD3)."""
    parsed = _parse_audit_args(arguments)
    if isinstance(parsed, MCPToolResult):
        return parsed
    uid, trust_filter, origin_filter, audit_limit = parsed

    listing_raw = getattr(memory_port, "list_entries", None)
    if listing_raw is None:
        return _error_result("memory_audit unavailable: list_entries not supported on this backend")
    listing = cast(
        "Callable[..., Awaitable[list[dict[str, object]]]]",
        listing_raw,
    )

    namespaces = _search_namespaces(
        user_id=uid,
        thread_id=arguments.get("thread_id", ""),
        org_id=arguments.get("org_id", ""),
    )
    collected = await _collect_audit_entries(
        listing,
        namespaces=namespaces,
        trust_filter=trust_filter,
        origin_filter=origin_filter,
        audit_limit=audit_limit,
    )
    payload = {
        "tool": "memory_audit",
        "user_id": uid,
        "trust_filter": trust_filter,
        "origin_filter": origin_filter or None,
        "entries": collected,
        "entry_count": len(collected),
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


def _parse_audit_args(
    arguments: dict[str, object],
) -> tuple[str, str, str, int] | MCPToolResult:
    user_id = arguments.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    trust_filter_raw = arguments.get("trust_filter", "low")
    trust_filter = str(trust_filter_raw).strip().lower() if trust_filter_raw is not None else "low"
    if trust_filter not in _VALID_AUDIT_TRUST_FILTERS:
        return _error_result("Invalid params: trust_filter must be low|inferred|quarantined|all")
    origin_filter_raw = arguments.get("origin_filter", "")
    origin_filter = str(origin_filter_raw).strip().lower() if isinstance(origin_filter_raw, str) else ""
    if origin_filter and origin_filter not in _VALID_AUDIT_ORIGINS:
        return _error_result("Invalid params: origin_filter must be user_hitl|extract|compact|system|legacy")
    try:
        audit_limit = max(1, min(int(str(arguments.get("limit", "32")).strip()), 128))
    except TypeError, ValueError:
        return _error_result("Invalid params: limit must be an integer between 1 and 128")
    return user_id.strip(), trust_filter, origin_filter, audit_limit


async def _collect_audit_entries(
    listing: Callable[..., Awaitable[list[dict[str, object]]]],
    *,
    namespaces: list[tuple[str, ...]],
    trust_filter: str,
    origin_filter: str,
    audit_limit: int,
) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for namespace in namespaces:
        rows = await listing(namespace=namespace, limit=audit_limit)
        for item in rows:
            row = _audit_row_from_item(
                item,
                namespace=namespace,
                trust_filter=trust_filter,
                origin_filter=origin_filter,
                seen_keys=seen_keys,
            )
            if row is None:
                continue
            collected.append(row)
            if len(collected) >= audit_limit:
                return collected
    return collected


def _audit_row_from_item(
    item: dict[str, object],
    *,
    namespace: tuple[str, ...],
    trust_filter: str,
    origin_filter: str,
    seen_keys: set[str],
) -> dict[str, object] | None:
    key = str(item.get("_entry_key") or "").strip()
    dedupe = f"{'/'.join(namespace)}::{key}"
    if not key or dedupe in seen_keys:
        return None
    trust = resolve_memory_trust(item)
    origin = resolve_memory_origin(item)
    if not _audit_trust_match(trust=trust, trust_filter=trust_filter):
        return None
    if origin_filter and origin != origin_filter:
        return None
    seen_keys.add(dedupe)
    return {
        "namespace": "/".join(namespace),
        "entry_key": key,
        "text": str(item.get("text", "")).strip(),
        "origin": origin,
        "trust": trust,
        "trust_score": memory_trust_score(trust),
        "created_at": str(item.get("_created_at") or "").strip() or None,
        "source_task_id": str(item.get("source_task_id") or "").strip() or None,
        "thread_id": str(item.get("thread_id") or "").strip() or None,
    }


async def memory_verify(
    memory_port: MemoryPort,
    arguments: dict[str, object],
) -> MCPToolResult:
    """Apply confirmed→verified or rejected→quarantined trust update (HITL outside)."""
    identity = _validate_save_identity(arguments)
    if isinstance(identity, MCPToolResult):
        return identity
    user_id, namespace_kind, scope_id, entry_key = identity

    verdict_raw = arguments.get("verdict")
    if not isinstance(verdict_raw, str) or verdict_raw.strip().lower() not in _VALID_VERIFY_VERDICTS:
        return _error_result("Invalid params: verdict must be confirmed|rejected")
    verdict = verdict_raw.strip().lower()

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

    try:
        namespace = resolve_memory_namespace(
            kind=namespace_kind,
            scope_id=scope_id,
            user_id=user_id,
        )
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    existing = await memory_port.get(namespace=namespace, key=entry_key)
    if existing is None:
        return _error_result(f"memory entry not found: {entry_key}")

    stored = {k: v for k, v in existing.items() if not str(k).startswith("_")}
    prior_origin = resolve_memory_origin(stored)
    prior_trust = resolve_memory_trust(stored)
    if verdict == "confirmed":
        stored[MEMORY_TRUST_KEY] = "verified"
        stored[MEMORY_EXPLICIT_WRITE_KEY] = True
        # Human confirmation upgrades trust; keep historical origin unless missing.
        if coerce_memory_origin(stored.get(MEMORY_ORIGIN_KEY)) is None:
            stored[MEMORY_ORIGIN_KEY] = "user_hitl"
    else:
        stored[MEMORY_TRUST_KEY] = "quarantined"

    await memory_port.put(namespace=namespace, key=entry_key, value=stored)
    new_trust = resolve_memory_trust(stored)
    new_origin = resolve_memory_origin(stored)
    logger.info(
        "memory_verify.applied",
        entry_key=entry_key[:128],
        verdict=verdict,
        prior_trust=prior_trust,
        new_trust=new_trust,
        prior_origin=prior_origin,
        new_origin=new_origin,
    )
    payload = {
        "tool": "memory_verify",
        "namespace": "/".join(namespace),
        "entry_key": entry_key,
        "verdict": verdict,
        "origin": new_origin,
        "trust": new_trust,
        "trust_score": memory_trust_score(new_trust),
        "status": "verified" if verdict == "confirmed" else "rejected",
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


def _audit_trust_match(*, trust: str, trust_filter: str) -> bool:
    if trust_filter == "all":
        return True
    if trust_filter == "low":
        return trust in {"inferred", "quarantined"}
    return trust == trust_filter


def _stamp_origin_trust(stored: dict[str, object]) -> None:
    """Ensure closed origin/trust axes on every MCP save (ADR 0008).

    Callers may pre-stamp (HITL / extract). Missing fields are inferred from
    ``explicit_write`` / ``source_task_id``; never invent ``verified`` for extract.
    """
    explicit = stored.get(MEMORY_EXPLICIT_WRITE_KEY)
    is_explicit = explicit is True or (isinstance(explicit, str) and explicit.strip().lower() in {"1", "true", "yes"})
    origin = coerce_memory_origin(stored.get(MEMORY_ORIGIN_KEY))
    trust = coerce_memory_trust(stored.get(MEMORY_TRUST_KEY))
    if origin is None:
        if is_explicit:
            origin = "user_hitl"
        elif str(stored.get("source_task_id", "")).strip():
            origin = "extract"
        else:
            origin = "system"
    if trust is None:
        trust = "verified" if is_explicit or origin in {"user_hitl", "system"} else "inferred"
        if origin == "extract":
            trust = "inferred"
    stored[MEMORY_ORIGIN_KEY] = origin
    stored[MEMORY_TRUST_KEY] = trust


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )
