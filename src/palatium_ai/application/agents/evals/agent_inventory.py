# src/palatium_ai/application/agents/evals/agent_inventory.py

"""W6 agent inventory — packages vs LangGraph vs off-graph pipelines (ADR-0009)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

AgentDisposition = Literal["keep", "reserve", "delete"]

#: Package folder names under ``application/agents/`` that ship a BaseAgent.
AGENT_PACKAGE_NAMES: Final[tuple[str, ...]] = (
    "intent_classifier",
    "context_enricher",  # continuation + weaving (two graph nodes, one package)
    "supervisor",
    "researcher",
    "coder",
    "analyst",
    "critic",
    "formatter",
    "memory_keeper",
    "text_ingestor",
)


@dataclass(frozen=True)
class AgentInventoryRow:
    """One inventory decision — no ``unknown`` allowed (W6.3)."""

    agent: str
    in_graph: bool
    used_in_tests: bool
    has_eval: bool
    disposition: AgentDisposition
    notes: str
    #: When to re-open the disposition (ADR-0010). Empty = graph keep, no reserve.
    review_trigger: str = ""


#: SoT for ADR-0009 «Agent inventory». Keep in sync with GraphAgents + AGENT_PACKAGES.
AGENT_INVENTORY: Final[tuple[AgentInventoryRow, ...]] = (
    AgentInventoryRow(
        agent="intent_classifier",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node intent_classifier",
    ),
    AgentInventoryRow(
        agent="context_enricher.continuation",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node context_enricher_continuation (package context_enricher)",
    ),
    AgentInventoryRow(
        agent="context_enricher.weaving",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node context_enricher_weaving (package context_enricher)",
    ),
    AgentInventoryRow(
        agent="supervisor",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node supervisor",
    ),
    AgentInventoryRow(
        agent="researcher",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node researcher (+ parallel_workers)",
    ),
    AgentInventoryRow(
        agent="coder",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node coder (draft-only)",
    ),
    AgentInventoryRow(
        agent="analyst",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node analyst (+ parallel_workers)",
    ),
    AgentInventoryRow(
        agent="critic",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node critic",
    ),
    AgentInventoryRow(
        agent="formatter",
        in_graph=True,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Graph node formatter",
    ),
    AgentInventoryRow(
        agent="memory_keeper",
        in_graph=False,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Off-graph sleep-time extract (MemoryExtractService); not a LangGraph node",
        review_trigger=(
            "Next agents audit-cycle (≤6 months from ADR-0010) or shared off-graph extract/ingest orchestrator — whichever first"
        ),
    ),
    AgentInventoryRow(
        agent="text_ingestor",
        in_graph=False,
        used_in_tests=True,
        has_eval=True,
        disposition="keep",
        notes="Off-graph document ingest (DocumentIngestService); not a LangGraph node",
        review_trigger=(
            "Next agents audit-cycle (≤6 months from ADR-0010) or shared off-graph extract/ingest orchestrator — whichever first"
        ),
    ),
)

GRAPH_AGENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "intent_agent",
        "supervisor_agent",
        "researcher_agent",
        "critic_agent",
        "formatter_agent",
        "coder_agent",
        "analyst_agent",
        "continuation_agent",
        "weaving_agent",
    }
)


__all__ = [
    "AGENT_INVENTORY",
    "AGENT_PACKAGE_NAMES",
    "GRAPH_AGENT_FIELDS",
    "AgentDisposition",
    "AgentInventoryRow",
]
