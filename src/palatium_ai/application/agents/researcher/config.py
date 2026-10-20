# src/palatium_ai/application/agents/researcher/config.py

"""Researcher AgentConfig (030)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.policies.researcher_tier import ResearcherTierPolicy
from palatium_ai.domain.policies.types import (
    CONTENT_GENERATION_CAPABILITY,
    DOCUMENT_GENERATION_CAPABILITY,
)

if TYPE_CHECKING:
    from palatium_ai.domain.policies.types import ExecutionStrategy

# >5 tools: Researcher is the sole MCP worker for EDMS + platform retrieval
# (knowledge/memory/graph/web/skills). Supervisor never gets execution tools (030).
RESEARCHER_CONFIG = AgentConfig(
    name="researcher",
    role="researcher",
    model_tier="mid",
    temperature=0.1,
    allowed_tools=(
        "mcp:edms.search_documents",
        "mcp:edms.archive_document",
        "mcp:analytics.get_sales_metrics",
        "mcp:platform.search_knowledge",
        "mcp:platform.search_memory",
        "mcp:platform.graph_query",
        "mcp:platform.skill_reference",
        "mcp:platform.web_fallback",
        "mcp:platform.read_attachment",
    ),
    timeout_seconds=90,
    max_retries=3,
    confidence_threshold=0.7,
)

# Align with Formatter source clip so full letters survive the handoff (065).
SUMMARY_MAX_CHARS = 8_000
#: A document read is evidence, not a search hit: the generic MCP envelope budget
#: (``MCP_TOOL_OUTPUT_MAX_CHARS``, 3000) reduces a thread-file re-read to a snippet.
#: Floor for ``platform.read_attachment`` output; the global knob may still raise it.
#: Kept below the turn's attachment budget (24k) so one document fits one prompt (065).
READ_ATTACHMENT_OUTPUT_MAX_CHARS = 12_000
RESEARCHER_DEFAULT_MAX_TOKENS = 2_048
RESEARCHER_GENERATION_MAX_TOKENS = 4_096

#: Host-local tool whose payload is document text rather than a search envelope (070).
_READ_ATTACHMENT_BINDING = ("platform", "read_attachment")


def researcher_tool_output_budget(
    *,
    server_name: str,
    tool_name: str,
    default_max_chars: int,
) -> int:
    """Char budget for one MCP payload in the synthesis prompt (065).

    ``read_attachment`` returns the document itself, so it is budgeted as evidence
    (``READ_ATTACHMENT_OUTPUT_MAX_CHARS`` floor); retrieval tools keep the smaller
    envelope budget configured for the agent.
    """
    if (server_name, tool_name) == _READ_ATTACHMENT_BINDING:
        return max(default_max_chars, READ_ATTACHMENT_OUTPUT_MAX_CHARS)
    return default_max_chars


_GENERATION_CAPS: frozenset[str] = frozenset(
    {
        CONTENT_GENERATION_CAPABILITY,
        DOCUMENT_GENERATION_CAPABILITY,
        "expand",  # prior elaboration needs headroom beyond default
    },
)


def researcher_completion_budget(candidate_capabilities: tuple[str, ...] | list[str]) -> int:
    """Higher completion ceiling for draft/compose/expand so bodies are not gateway-truncated."""
    caps = {str(c).strip().lower() for c in candidate_capabilities if str(c).strip()}
    if caps & _GENERATION_CAPS:
        return RESEARCHER_GENERATION_MAX_TOKENS
    return RESEARCHER_DEFAULT_MAX_TOKENS


def researcher_llm_config(
    config: AgentConfig,
    *,
    strategy: ExecutionStrategy | str | None,
) -> AgentConfig:
    """Copy of agent config with tier from ResearcherTierPolicy."""
    decision = ResearcherTierPolicy.decide(strategy=strategy)
    if decision.model_tier == config.model_tier:
        return config
    return config.model_copy(update={"model_tier": decision.model_tier})
