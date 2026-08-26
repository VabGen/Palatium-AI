# src/palatium_ai/infrastructure/memory/checkpoint_serde.py

"""LangGraph checkpoint serde with explicit msgpack allowlist for domain types.

Without an allowlist, JsonPlusSerializer warns (and later may block) on every
Pydantic model in AgentGraphState. Allowlisting is the Zero-Trust equivalent of
Factor 5: only known contracts may revive from checkpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

if TYPE_CHECKING:
    from langgraph.checkpoint.serde.base import SerializerProtocol

# (module, class_name) pairs that may appear in AgentGraphState channels.
# Keep in sync when adding new domain models to graph state.
CHECKPOINT_MSGPACK_ALLOWLIST: tuple[tuple[str, str], ...] = (
    # Memory / dialog
    ("palatium_ai.domain.memory.turns", "DialogTurn"),
    ("palatium_ai.domain.memory.turns", "DialogTurnWindow"),
    ("palatium_ai.domain.memory.recall", "MemoryHit"),
    ("palatium_ai.domain.memory.recall", "MemoryRecallBundle"),
    ("palatium_ai.domain.memory.budget", "MemoryPromptBudget"),
    ("palatium_ai.domain.memory.contextualizer", "ContextualizerOutput"),
    ("palatium_ai.domain.memory.contextualizer", "ContextualizerTaskResult"),
    ("palatium_ai.domain.memory.continuity", "EffectiveRoutingIntent"),
    # Agents
    ("palatium_ai.domain.agents.intent", "IntentClassifierOutput"),
    ("palatium_ai.domain.agents.intent", "IntentTaskResult"),
    ("palatium_ai.domain.agents.supervisor", "SupervisorOutput"),
    ("palatium_ai.domain.agents.supervisor", "SupervisorTaskResult"),
    ("palatium_ai.domain.agents.context_packet", "ContextPacket"),
    ("palatium_ai.domain.agents.context_weaver", "ContextWeaverOutput"),
    ("palatium_ai.domain.agents.context_weaver", "ContextWeaverTaskResult"),
    ("palatium_ai.domain.agents.researcher", "ResearcherOutput"),
    ("palatium_ai.domain.agents.researcher", "ResearcherTaskResult"),
    ("palatium_ai.domain.agents.critic", "CriticOutput"),
    ("palatium_ai.domain.agents.critic", "CriticTaskResult"),
    ("palatium_ai.domain.agents.formatter", "FormatterTaskResult"),
    # MCP execution plans (inside ContextPacket / ContextWeaver)
    ("palatium_ai.domain.mcp.models", "ToolExecutionPlan"),
    ("palatium_ai.domain.mcp.models", "ExecutionPlanBundle"),
    # ContentDocument tree (Formatter output)
    ("palatium_ai.domain.content.content_document", "HeadingBlock"),
    ("palatium_ai.domain.content.content_document", "ParagraphBlock"),
    ("palatium_ai.domain.content.content_document", "ListItem"),
    ("palatium_ai.domain.content.content_document", "ListBlock"),
    ("palatium_ai.domain.content.content_document", "TableBlock"),
    ("palatium_ai.domain.content.content_document", "CalloutBlock"),
    ("palatium_ai.domain.content.content_document", "CodeBlock"),
    ("palatium_ai.domain.content.content_document", "FormulaBlock"),
    ("palatium_ai.domain.content.content_document", "KeyValueItem"),
    ("palatium_ai.domain.content.content_document", "KeyValueBlock"),
    ("palatium_ai.domain.content.content_document", "StepItem"),
    ("palatium_ai.domain.content.content_document", "StepsBlock"),
    ("palatium_ai.domain.content.content_document", "ChartSeries"),
    ("palatium_ai.domain.content.content_document", "ChartBlock"),
    ("palatium_ai.domain.content.content_document", "DividerBlock"),
    ("palatium_ai.domain.content.content_document", "WidgetBlock"),
    ("palatium_ai.domain.content.content_document", "ActionSpec"),
    ("palatium_ai.domain.content.content_document", "DocumentMeta"),
    ("palatium_ai.domain.content.content_document", "ContentDocument"),
    # HITL (attached to FormatterTaskResult)
    ("palatium_ai.domain.hitl.cards", "HITLOption"),
    ("palatium_ai.domain.hitl.cards", "HITLCardView"),
)


def build_checkpoint_serde() -> SerializerProtocol:
    """JsonPlusSerializer with explicit allowlist (no silent unregistered types)."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_MSGPACK_ALLOWLIST)
