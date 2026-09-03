# src/palatium_ai/domain/mcp/tool_policy.py

"""MCP tool ACL patterns and side-effect / HITL-before policy (Zero Trust).

Platform registration contract (every MCP tool used in production):
1. Stub/server implements the tool + inputSchema.
2. Add a ``PlatformToolPin`` here with side_effect, schema fingerprint,
   risk_tier, and requires_hitl (explicit; never trust server attestation).
3. Add ``mcp:<server>.<tool>`` to Researcher ``allowed_tools``.
4. Wire server URL in ``MCP_SERVERS``.

Unpinned or schema-mismatched tools classify as ``unknown`` → HITL interrupt.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.external_schemas import (
    ANALYTICS_SALES_METRICS_SCHEMA,
    EDMS_ARCHIVE_DOCUMENT_SCHEMA,
    EDMS_SEARCH_DOCUMENTS_SCHEMA,
)
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.platform_schemas import (
    PLATFORM_CONSOLIDATE_MEMORY_SCHEMA,
    PLATFORM_FORGET_MEMORY_SCHEMA,
    PLATFORM_GRAPH_QUERY_SCHEMA,
    PLATFORM_INGEST_DOCUMENT_SCHEMA,
    PLATFORM_SAVE_MEMORY_SCHEMA,
    PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
    PLATFORM_SEARCH_MEMORY_SCHEMA,
    PLATFORM_WEB_FALLBACK_SCHEMA,
)

SideEffectClass = Literal["read", "write", "unknown"]
ToolRiskTier = Literal["low", "medium", "high"]


def schema_fingerprint(schema: dict[str, object]) -> str:
    """Stable SHA-256 over canonical JSON Schema object."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PlatformToolPin(BaseModel):
    """Platform-owned registration pin: side-effect + risk + HITL bound to schema."""

    model_config = {"frozen": True}

    side_effect: SideEffectClass
    schema_fingerprint: str = Field(min_length=64, max_length=64)
    risk_tier: ToolRiskTier
    requires_hitl: bool
    irreversible: bool = False


# Platform-pinned tools. MCP server self-attestation is never trusted
# to lower risk. Pin applies only when discovered inputSchema fingerprint matches.
_PLATFORM_SIDE_EFFECTS: dict[str, PlatformToolPin] = {
    "mcp:edms.search_documents": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(EDMS_SEARCH_DOCUMENTS_SCHEMA),
        risk_tier="low",
        requires_hitl=False,
    ),
    "mcp:edms.archive_document": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(EDMS_ARCHIVE_DOCUMENT_SCHEMA),
        risk_tier="high",
        requires_hitl=True,
        irreversible=True,
    ),
    "mcp:analytics.get_sales_metrics": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(ANALYTICS_SALES_METRICS_SCHEMA),
        risk_tier="low",
        requires_hitl=False,
    ),
    "mcp:platform.ingest_document": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(PLATFORM_INGEST_DOCUMENT_SCHEMA),
        risk_tier="high",
        requires_hitl=True,
        irreversible=True,
    ),
    "mcp:platform.search_knowledge": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(PLATFORM_SEARCH_KNOWLEDGE_SCHEMA),
        risk_tier="low",
        requires_hitl=False,
    ),
    "mcp:platform.search_memory": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(PLATFORM_SEARCH_MEMORY_SCHEMA),
        risk_tier="low",
        requires_hitl=False,
    ),
    "mcp:platform.save_memory": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(PLATFORM_SAVE_MEMORY_SCHEMA),
        risk_tier="medium",
        requires_hitl=True,
    ),
    "mcp:platform.forget_memory": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(PLATFORM_FORGET_MEMORY_SCHEMA),
        risk_tier="medium",
        requires_hitl=True,
    ),
    "mcp:platform.consolidate_memory": PlatformToolPin(
        side_effect="write",
        schema_fingerprint=schema_fingerprint(PLATFORM_CONSOLIDATE_MEMORY_SCHEMA),
        risk_tier="medium",
        requires_hitl=True,
    ),
    "mcp:platform.graph_query": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(PLATFORM_GRAPH_QUERY_SCHEMA),
        risk_tier="low",
        requires_hitl=False,
    ),
    "mcp:platform.web_fallback": PlatformToolPin(
        side_effect="read",
        schema_fingerprint=schema_fingerprint(PLATFORM_WEB_FALLBACK_SCHEMA),
        risk_tier="medium",
        requires_hitl=False,
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
        """Legacy wildcard form — not accepted by ACL (exact pins only)."""
        return f"mcp:{self.server_name}.*"


def mcp_tool_ref(server_name: str, tool_name: str) -> McpToolRef:
    """Build a validated MCP tool reference."""
    return McpToolRef(server_name=server_name, tool_name=tool_name)


def iter_platform_pins() -> tuple[tuple[str, PlatformToolPin], ...]:
    """Stable view of registered platform pins (onboarding / audits)."""
    return tuple(sorted(_PLATFORM_SIDE_EFFECTS.items(), key=lambda item: item[0]))


def resolve_platform_pin(
    descriptor: MCPToolDescriptor,
    *,
    server_name: str | None = None,
) -> PlatformToolPin | None:
    """Return matching platform pin or None (unpinned / schema mismatch)."""
    if not server_name:
        return None
    ref = mcp_tool_ref(server_name, descriptor.name)
    pinned = _PLATFORM_SIDE_EFFECTS.get(ref.acl_key)
    if pinned is None:
        return None
    actual = schema_fingerprint(dict(descriptor.input_schema))
    if secrets.compare_digest(actual, pinned.schema_fingerprint):
        return pinned
    return None


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
    - MCP requires exact `mcp:<server>.<tool>` (wildcards rejected).
    """
    allowed = frozenset(allowed_tools)
    if tool_name != "mcp.call":
        return tool_name in allowed

    if server_name is None or mcp_tool_name is None:
        return False
    ref = mcp_tool_ref(server_name, mcp_tool_name)
    return ref.acl_key in allowed


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
    pinned = resolve_platform_pin(descriptor, server_name=server_name)
    if pinned is not None:
        return pinned.side_effect
    return "unknown"


def classify_risk_tier(
    descriptor: MCPToolDescriptor,
    *,
    side_effect: SideEffectClass | None = None,
    server_name: str | None = None,
) -> ToolRiskTier:
    """Map platform pin risk_tier; else derive from side-effect class."""
    pinned = resolve_platform_pin(descriptor, server_name=server_name)
    if pinned is not None:
        return pinned.risk_tier
    effect = side_effect if side_effect is not None else classify_side_effect(descriptor, server_name=server_name)
    if effect == "write":
        return "high"
    if effect == "unknown":
        return "medium"
    return "low"


def requires_interrupt_before_call(
    side_effect: SideEffectClass,
    *,
    pin: PlatformToolPin | None = None,
) -> bool:
    """Whether human approval is required before the MCP call.

    Prefer explicit ``pin.requires_hitl`` when the tool is platform-pinned.
    Unpinned calls always interrupt — never trust a free-floating side_effect claim.
    """
    _ = side_effect
    if pin is not None:
        return pin.requires_hitl
    return True


def risk_score_for_tier(tier: ToolRiskTier) -> float:
    """Numeric risk for HITL card expiry / escalation policy."""
    if tier == "high":
        return 0.85
    if tier == "medium":
        return 0.55
    return 0.2


def binding_hitl_metadata(
    descriptor: MCPToolDescriptor,
    *,
    server_name: str,
) -> tuple[SideEffectClass, ToolRiskTier, bool]:
    """side_effect, risk_tier, requires_hitl for capability index / planners."""
    pinned = resolve_platform_pin(descriptor, server_name=server_name)
    if pinned is not None:
        return pinned.side_effect, pinned.risk_tier, pinned.requires_hitl
    return "unknown", "medium", True


def binding_hitl_metadata_for_ref(
    *,
    server_name: str,
    tool_name: str,
) -> tuple[SideEffectClass, ToolRiskTier, bool]:
    """Discovery-time HITL hints from platform pin name (no schema yet).

    Execution must still call ``resolve_platform_pin`` with the full descriptor —
    schema fingerprint is verified only at call time.
    """
    ref = mcp_tool_ref(server_name, tool_name)
    pinned = _PLATFORM_SIDE_EFFECTS.get(ref.acl_key)
    if pinned is not None:
        return pinned.side_effect, pinned.risk_tier, pinned.requires_hitl
    return "unknown", "medium", True
