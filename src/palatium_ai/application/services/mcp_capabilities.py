# src/palatium_ai/application/services/mcp_capabilities.py

"""Generic capability discovery and resolution over MCP tools."""

from __future__ import annotations

import asyncio
import re
import time

from typing import TYPE_CHECKING

import structlog

from palatium_ai.domain.mcp.models import MCPCapabilityBinding, MCPToolSummary
from palatium_ai.domain.mcp.tool_policy import binding_hitl_metadata_for_ref

if TYPE_CHECKING:
    from palatium_ai.domain.ports.mcp import MCPRegistryPort

logger = structlog.get_logger(__name__)

# Letters (any script) of length >= 3 — ASCII-only left Russian/CJK asks with empty task_terms.
_WORD_PATTERN = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_DISCOVER_CACHE_TTL_SECONDS = 60.0


class MCPCapabilityIndex:
    """Capability map from MCP tool *summaries* (progressive disclosure; no schema dump)."""

    def __init__(self, registry: MCPRegistryPort, *, cache_ttl_seconds: float = _DISCOVER_CACHE_TTL_SECONDS) -> None:
        self._registry = registry
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cached_bindings: list[MCPCapabilityBinding] | None = None
        self._cached_at: float = 0.0

    async def warm_cache(self) -> int:
        """Prefetch capability index at startup (non-blocking for first request)."""
        bindings = await self.discover(force_refresh=True)
        return len(bindings)

    async def resolve_best(
        self,
        task_text: str,
        requested_capabilities: tuple[str, ...],
    ) -> MCPCapabilityBinding | None:
        """Pick best binding: Intent tags filter/boost; task text must evidence the tool.

        Intent ``candidate_capabilities`` alone must never select a tool — that caused
        false MCP calls on knowledge/rewrite asks that merely tagged ``search``.
        """
        discovered = await self.discover()
        requested = _normalize_terms(requested_capabilities)
        task_terms = _extract_terms(task_text)

        scored: list[tuple[int, MCPCapabilityBinding]] = []
        for binding in discovered:
            tool_terms = _binding_terms(binding)
            overlap = task_terms & tool_terms
            if not overlap:
                # No lexical evidence in the user ask → do not bind this tool.
                continue
            score = len(overlap)
            capability = binding.capability.lower()
            if capability in requested:
                score += 10
            elif requested:
                # Requested tags present but this binding is outside them — deprioritize.
                score -= 5
            if score > 0:
                scored.append((score, binding))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    async def discover(self, *, force_refresh: bool = False) -> list[MCPCapabilityBinding]:
        """Build capability -> server/tool from summaries (TTL cache)."""
        now = time.time()
        if not force_refresh and self._cached_bindings is not None and now - self._cached_at < self._cache_ttl_seconds:
            return list(self._cached_bindings)

        bindings: list[MCPCapabilityBinding] = []
        server_names = self._registry.list_servers()
        listed = await asyncio.gather(
            *[self._safe_list_summaries(server_name) for server_name in server_names],
        )
        for server_name, tools in zip(server_names, listed, strict=True):
            for tool in tools:
                bindings.extend(_summary_to_bindings(server_name, tool))

        self._cached_bindings = bindings
        self._cached_at = now
        return list(bindings)

    async def _safe_list_summaries(self, server_name: str) -> list[MCPToolSummary]:
        try:
            return await self._registry.list_tool_summaries(server_name)
        except Exception as exc:
            logger.warning(
                "MCP capability discovery skipped server",
                server=server_name,
                error=str(exc),
            )
            return []


def _summary_to_bindings(server_name: str, tool: MCPToolSummary) -> list[MCPCapabilityBinding]:
    """Extract capability tags from a summary (name/description/property names only)."""
    terms = _extract_summary_terms(tool)
    side_effect, risk_tier, requires_hitl = binding_hitl_metadata_for_ref(
        server_name=server_name,
        tool_name=tool.name,
    )
    return [
        MCPCapabilityBinding(
            capability=term,
            server_name=server_name,
            tool_name=tool.name,
            description=tool.description,
            side_effect=side_effect,
            risk_tier=risk_tier,
            requires_hitl=requires_hitl,
        )
        for term in sorted(terms)
    ]


def _binding_terms(binding: MCPCapabilityBinding) -> set[str]:
    """Lexical terms for scoring a binding against the user ask."""
    parts = [binding.capability, binding.tool_name, binding.description or ""]
    return _extract_terms(" ".join(parts))


def _extract_summary_terms(tool: MCPToolSummary) -> set[str]:
    """Terms from name, description, and schema property *names* (not full schema)."""
    raw_parts = [tool.name, tool.description, *tool.property_names]
    return _extract_terms(" ".join(raw_parts))


def _extract_terms(text: str) -> set[str]:
    """Нормализует текст в множество generic capability terms (any script)."""
    raw_terms = {token.lower().replace("_", " ") for token in _WORD_PATTERN.findall(text)}
    normalized: set[str] = set()
    for term in raw_terms:
        for part in term.split():
            if len(part) >= 3:
                normalized.add(part)
    return normalized


def _normalize_terms(capabilities: tuple[str, ...]) -> set[str]:
    """Нормализует requested capability tags."""
    normalized: set[str] = set()
    for capability in capabilities:
        normalized.update(_extract_terms(capability))
    return normalized
