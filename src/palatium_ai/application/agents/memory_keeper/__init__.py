# src/palatium_ai/application/agents/memory_keeper/__init__.py

"""MemoryKeeper agent package (030).

# reserved for future: not a LangGraph node — keep as off-graph sleep-time extract
# worker (MemoryExtractService / MCP extract_transcript_memories). Do not delete
# without ADR-0009 / ADR-0010 inventory update.
# Review trigger: next agents audit-cycle (≤6 months from ADR-0010) OR introduction
# of a shared off-graph extract/ingest orchestrator — whichever comes first.
"""

from palatium_ai.application.agents.memory_keeper.agent import MemoryKeeperAgent
from palatium_ai.application.agents.memory_keeper.config import MEMORY_KEEPER_CONFIG

__all__ = ["MEMORY_KEEPER_CONFIG", "MemoryKeeperAgent"]
