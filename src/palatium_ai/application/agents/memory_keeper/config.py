# src/palatium_ai/application/agents/memory_keeper/config.py

"""MemoryKeeper AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

MEMORY_KEEPER_CONFIG = AgentConfig(
    name="memory_keeper",
    role="memory_keeper",
    model_tier="frontier",
    temperature=0.0,
    allowed_tools=("mcp:platform.save_memory",),
    timeout_seconds=120,
    max_retries=2,
    confidence_threshold=0.7,
)

MAX_EXISTING_MEMORIES = 20
MEMORY_KINDS = frozenset({"fact", "preference", "entity", "summary"})
