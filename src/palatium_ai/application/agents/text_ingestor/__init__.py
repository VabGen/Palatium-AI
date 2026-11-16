# src/palatium_ai/application/agents/text_ingestor/__init__.py

"""TextIngestor agent package (030).

# reserved for future: not a LangGraph node — keep as off-graph document ingest
# worker (DocumentIngestService). Do not delete without ADR-0009 / ADR-0010 inventory
# update.
# Review trigger: next agents audit-cycle (≤6 months from ADR-0010) OR introduction
# of a shared off-graph extract/ingest orchestrator — whichever comes first.
"""

from palatium_ai.application.agents.text_ingestor.agent import TextIngestorAgent
from palatium_ai.application.agents.text_ingestor.config import TEXT_INGESTOR_CONFIG

__all__ = ["TEXT_INGESTOR_CONFIG", "TextIngestorAgent"]
