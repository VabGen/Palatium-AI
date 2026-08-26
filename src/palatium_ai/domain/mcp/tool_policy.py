# src/palatium_ai/domain/mcp/tool_policy.py

"""MCP tool ACL patterns and side-effect / HITL-before policy (Zero Trust)."""

from __future__ import annotations

import hashlib
import json
import secrets

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.models import MCPToolDescriptor

SideEffectClass = Literal["read", "write", "unknown"]
ToolRiskTier = Literal["low", "medium", "high"]

# Canonical inputSchema for pinned read tools (must match discovered descriptor).
_EDMS_SEARCH_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Search string for EDMS documents.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_ANALYTICS_METRICS_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "minLength": 1,
            "description": "Reporting period (e.g. 2025-Q1).",
        },
    },
    "required": ["period"],
    "additionalProperties": False,
}


_EDMS_ARCHIVE_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "document_id": {
            "type": "string",
            "minLength": 1,
            "description": "EDMS document identifier to archive.",
        },
    },
    "required": ["document_id"],
    "additionalProperties": False,
}


def schema_fingerprint(schema: dict[str, object]) -> str:
    """Stable SHA-256 over canonical JSON Schema object."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PlatformToolPin(BaseModel):
    """Platform-owned side-effect pin bound to an expected inputSchema fingerprint."""

    model_config = {"frozen": True}

    side_effect: SideEffectClass
    schema_fingerprint: str = Field(min_length=64, max_length=64)


# Platform-pinned side effects. MCP server self-attestation is never trusted
# to lower risk. Pin applies only when discovered inputSchema fingerprint matches.
_PLATFORM_SIDE_EFFECTS: dict[str, PlatformToolPin] = {
    "mcp:edms.search_documents": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(_EDMS_SEARCH_SCHEMA),
    ),
    "mcp:edms.archive_document": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(_EDMS_ARCHIVE_SCHEMA),
    ),
    "mcp:analytics.get_sales_metrics": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(_ANALYTICS_METRICS_SCHEMA),
    ),
}


class McpToolRef(BaseModel):
    """Resolved MCP tool identity for ACL / interrupt payloads."""

    model_config = {"frozen": True}

    server_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)

    @property
    def acl_key(self) -> str:
        """Canonical allow-list key: mcp:<server>.<tool>."""
        return f"mcp:{self.server_name}.{self.tool_name}"

    @property
    def server_wildcard(self) -> str:
        """Server-scoped wildcard: mcp:<server>.*."""
        return f"mcp:{self.server_name}.*"


def mcp_tool_ref(server_name: str, tool_name: str) -> McpToolRef:
    """Build a validated MCP tool reference."""
    return McpToolRef(server_name=server_name, tool_name=tool_name)


def is_tool_invocation_allowed(
    allowed_tools: frozenset[str] | tuple[str, ...],
    *,
    tool_name: str,
    server_name: str | None = None,
    mcp_tool_name: str | None = None,
) -> bool:
    """Return whether the invocation matches AgentConfig.allowed_tools.

    Rules:
    - Exact match on `tool_name` for non-MCP tools.
    - `mcp.call` alone never authorizes a concrete server/tool.
    - MCP requires `mcp:<server>.<tool>`, `mcp:<server>.*`, or `mcp:*`.
    """
    allowed = frozenset(allowed_tools)
    if tool_name != "mcp.call":
        return tool_name in allowed

    if server_name is None or mcp_tool_name is None:
        return False
    ref = mcp_tool_ref(server_name, mcp_tool_name)
    return bool(allowed & {ref.acl_key, ref.server_wildcard, "mcp:*"})


def classify_side_effect(
    descriptor: MCPToolDescriptor,
    *,
    server_name: str | None = None,
) -> SideEffectClass:
    """Classify side effects from the platform catalog only (fail closed).

    `descriptor.side_effect` and MCP annotations are untrusted input from the
    server. Known tools are pinned **only** when inputSchema fingerprint matches;
    everything else is ``unknown`` → HITL.
    """
    if server_name:
        ref = mcp_tool_ref(server_name, descriptor.name)
        pinned = _PLATFORM_SIDE_EFFECTS.get(ref.acl_key)
        if pinned is not None:
            actual = schema_fingerprint(dict(descriptor.input_schema))
            if secrets.compare_digest(actual, pinned.schema_fingerprint):
                return pinned.side_effect
    return "unknown"


def classify_risk_tier(
    descriptor: MCPToolDescriptor,
    *,
    side_effect: SideEffectClass | None = None,
    server_name: str | None = None,
) -> ToolRiskTier:
    """Map platform side-effect class to HITL risk tier (ignore server riskTier)."""
    effect = side_effect if side_effect is not None else classify_side_effect(descriptor, server_name=server_name)
    if effect == "write":
        return "high"
    if effect == "unknown":
        return "medium"
    return "low"


def requires_interrupt_before_call(side_effect: SideEffectClass) -> bool:
    """Write/unknown tools must pause for human approval before execution."""
    return side_effect in {"write", "unknown"}


def risk_score_for_tier(tier: ToolRiskTier) -> float:
    """Numeric risk for HITL card expiry / escalation policy."""
    if tier == "high":
        return 0.85
    if tier == "medium":
        return 0.55
    return 0.2
