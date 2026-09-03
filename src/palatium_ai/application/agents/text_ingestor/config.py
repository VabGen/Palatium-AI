# src/palatium_ai/application/agents/text_ingestor/config.py

"""TextIngestor AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

TEXT_INGESTOR_CONFIG = AgentConfig(
    name="text_ingestor",
    role="text_ingestor",
    model_tier="small",
    temperature=0.0,
    allowed_tools=("mcp:platform.ingest_document",),
    timeout_seconds=120,
    max_retries=1,
    confidence_threshold=0.7,
)

DEFAULT_MAX_CHUNK_CHARS = 1500
CHUNK_OVERLAP_CHARS = 100
MAX_CHUNKS_FOR_CONTEXT_PREFIX = 16
# confidence при enrich: доля чанков с непустым prefix (logprobs на small tier недоступны, 030.4).
