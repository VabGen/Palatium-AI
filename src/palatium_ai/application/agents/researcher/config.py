# src/palatium_ai/application/agents/researcher/config.py

"""Researcher AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

# >5 tools: Researcher is the sole MCP worker for EDMS + platform retrieval
# (knowledge/memory/graph/web). Supervisor never gets execution tools (030).
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
        "mcp:platform.web_fallback",
    ),
    timeout_seconds=90,
    max_retries=3,
    confidence_threshold=0.7,
)

SUMMARY_MAX_CHARS = 4000
