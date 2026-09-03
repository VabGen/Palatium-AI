# src/palatium_ai/domain/policies/memory_namespace.py

"""Bind memory namespace scope_id to authenticated principal (020/060).

Client-supplied ``scope_id`` is not a trust boundary: user/org/thread scopes
must match the caller identity / session thread, otherwise IDOR is trivial.

Also binds tenant-scoped platform MCP args (``user_id`` / ``org_id`` / ``thread_id``)
from trusted actor context before tool execution.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field


class MemoryNamespaceBinding(BaseModel):
    """Resolved namespace kind + bound scope after ownership checks."""

    model_config = {"frozen": True}

    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)


class MemoryNamespacePolicy:
    """Pure ownership policy for memory write/forget namespaces + MCP actor bind."""

    _VALID_KINDS = frozenset({"thread", "user", "org"})
    _TENANT_USER_TOOLS = frozenset(
        {
            "search_memory",
            "search_knowledge",
            "graph_query",
            "web_fallback",
            "ingest_document",
            "consolidate_memory",
        }
    )

    @staticmethod
    def bind_scope(
        *,
        namespace_kind: str,
        requested_scope_id: str,
        owner_user_id: str,
        org_id: str | None,
        thread_id: str,
    ) -> MemoryNamespaceBinding:
        """Return bound scope or raise ValueError on ownership mismatch."""
        kind = namespace_kind.strip().lower()
        if kind not in MemoryNamespacePolicy._VALID_KINDS:
            msg = "namespace_kind must be thread|user|org"
            raise ValueError(msg)

        requested = requested_scope_id.strip()
        owner = owner_user_id.strip()
        thread = thread_id.strip()
        if not owner:
            msg = "owner_user_id is required"
            raise ValueError(msg)

        if kind == "user":
            if requested and requested != owner:
                msg = "scope_id must match authenticated user"
                raise ValueError(msg)
            return MemoryNamespaceBinding(namespace_kind=kind, scope_id=owner)

        if kind == "thread":
            if not thread:
                msg = "thread_id is required for thread namespace"
                raise ValueError(msg)
            if requested and requested != thread:
                msg = "scope_id must match thread_id"
                raise ValueError(msg)
            return MemoryNamespaceBinding(namespace_kind=kind, scope_id=thread)

        # org
        tenant = (org_id or "").strip()
        if not tenant:
            msg = "org namespace requires authenticated org_id"
            raise ValueError(msg)
        if requested and requested != tenant:
            msg = "scope_id must match authenticated org"
            raise ValueError(msg)
        return MemoryNamespaceBinding(namespace_kind=kind, scope_id=tenant)

    @staticmethod
    def mcp_user_scope_consistent(*, namespace_kind: str, scope_id: str, user_id: str) -> bool:
        """Defense-in-depth for MCP: user namespace scope must equal user_id."""
        if namespace_kind.strip().lower() != "user":
            return True
        return scope_id.strip() == user_id.strip()

    @staticmethod
    def mcp_org_scope_consistent(*, namespace_kind: str, scope_id: str, org_id: str | None) -> bool:
        """Org namespace writes require explicit org_id claim equal to scope_id."""
        if namespace_kind.strip().lower() != "org":
            return True
        claim = (org_id or "").strip()
        return bool(claim) and claim == scope_id.strip()

    @staticmethod
    def bind_mcp_memory_arguments(
        *,
        tool_name: str,
        arguments: dict[str, object],
        actor_user_id: str = "",
        actor_org_id: str = "",
        actor_thread_id: str = "",
    ) -> dict[str, object]:
        """Overwrite platform MCP tenant fields from trusted actor context.

        Raises ValueError when tenant-scoped tools lack the required actor claim.
        """
        user_actor = actor_user_id.strip()
        org_actor = actor_org_id.strip()
        thread_actor = actor_thread_id.strip()

        if tool_name in MemoryNamespacePolicy._TENANT_USER_TOOLS:
            return MemoryNamespacePolicy._bind_tenant_user_tool(
                tool_name=tool_name,
                arguments=arguments,
                user_actor=user_actor,
                org_actor=org_actor,
                thread_actor=thread_actor,
            )

        if tool_name not in {"save_memory", "forget_memory"}:
            return dict(arguments)

        return MemoryNamespacePolicy._bind_memory_mutation_args(
            arguments=arguments,
            user_actor=user_actor,
            org_actor=org_actor,
            thread_actor=thread_actor,
        )

    @staticmethod
    def _bind_memory_mutation_args(
        *,
        arguments: dict[str, object],
        user_actor: str,
        org_actor: str,
        thread_actor: str,
    ) -> dict[str, object]:
        args = dict(arguments)
        kind = str(args.get("namespace_kind", "")).strip().lower()

        if kind == "user":
            if not user_actor:
                msg = "actor_user_id required for user namespace memory writes"
                raise ValueError(msg)
            args["user_id"] = user_actor
            args["scope_id"] = user_actor
            return args

        if kind == "org":
            if not org_actor:
                msg = "actor_org_id required for org namespace memory writes"
                raise ValueError(msg)
            args["org_id"] = org_actor
            args["scope_id"] = org_actor
            if user_actor:
                args["user_id"] = user_actor
            return args

        if kind == "thread":
            if thread_actor:
                args["scope_id"] = thread_actor
            if user_actor:
                args["user_id"] = user_actor
            return args

        return args

    @staticmethod
    def _bind_tenant_user_tool(
        *,
        tool_name: str,
        arguments: dict[str, object],
        user_actor: str,
        org_actor: str,
        thread_actor: str,
    ) -> dict[str, object]:
        if not user_actor:
            msg = f"actor_user_id required for {tool_name}"
            raise ValueError(msg)

        args = dict(arguments)
        args["user_id"] = user_actor

        if tool_name in {"search_memory", "search_knowledge", "ingest_document", "consolidate_memory"} and thread_actor:
            args["thread_id"] = thread_actor

        if tool_name in {"search_memory", "consolidate_memory"}:
            if org_actor:
                args["org_id"] = org_actor
            else:
                args.pop("org_id", None)

        if tool_name == "graph_query":
            args["params_json"] = MemoryNamespacePolicy._force_params_user_id(
                args.get("params_json", "{}"),
                user_actor=user_actor,
            )

        return args

    @staticmethod
    def _force_params_user_id(params_json: object, *, user_actor: str) -> str:
        raw: object
        if isinstance(params_json, str) and params_json.strip():
            try:
                raw = json.loads(params_json)
            except json.JSONDecodeError:
                raw = {}
        elif isinstance(params_json, dict):
            raw = params_json
        else:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        forced = {str(key): value for key, value in raw.items()}
        forced["user_id"] = user_actor
        return json.dumps(forced, ensure_ascii=False)
