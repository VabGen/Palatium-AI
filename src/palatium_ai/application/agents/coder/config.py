# src/palatium_ai/application/agents/coder/config.py

"""Coder AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

# No execution tools: sandbox/code-exec requires HITL + sandboxed runtime (020).
# Coder produces drafts/plans only until a sandbox MCP tool is added to 070.
CODER_CONFIG = AgentConfig(
    name="coder",
    role="coder",
    model_tier="mid",
    temperature=0.1,
    allowed_tools=(),
    timeout_seconds=90,
    max_retries=2,
    confidence_threshold=0.7,
)
