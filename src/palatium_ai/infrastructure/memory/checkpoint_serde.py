# src/palatium_ai/infrastructure/memory/checkpoint_serde.py

"""LangGraph checkpoint serde with explicit msgpack allowlist for domain types.

Without an allowlist, JsonPlusSerializer warns (and later may block) on every
Pydantic model in AgentGraphState. Allowlisting is the Zero-Trust equivalent of
Factor 5: only known contracts may revive from checkpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from palatium_ai.core.types.graph_nodes import LEGACY_GRAPH_NODE_IDS

if TYPE_CHECKING:
    from langgraph.checkpoint.serde.base import SerializerProtocol

# (module, class_name) pairs that may appear in AgentGraphState channels.
# Keep in sync when adding new domain models to graph state.
CHECKPOINT_MSGPACK_ALLOWLIST: tuple[tuple[str, str], ...] = (
    # Postgres AsyncPostgresSaver / asyncpg may revive UUID as this class.
    ("asyncpg.pgproto.pgproto", "UUID"),
    ("uuid", "UUID"),
    # Memory / dialog
    ("palatium_ai.domain.memory.turns", "DialogTurn"),
    ("palatium_ai.domain.memory.turns", "DialogTurnWindow"),
    ("palatium_ai.domain.memory.recall", "MemoryHit"),
    ("palatium_ai.domain.memory.recall", "MemoryRecallBundle"),
    ("palatium_ai.domain.memory.budget", "MemoryPromptBudget"),
    ("palatium_ai.domain.memory.contextualizer", "ContextualizerOutput"),
    ("palatium_ai.domain.memory.contextualizer", "ContextualizerTaskResult"),
    ("palatium_ai.domain.policies.continuity", "EffectiveRoutingIntent"),
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


def _remap_legacy_node_id(node_id: str) -> str:
    return LEGACY_GRAPH_NODE_IDS.get(node_id, node_id)


# Keys whose value *is* a graph node id (LangGraph checkpoint payloads). ``next`` is
# handled separately: it carries a collection of ids and keeps its container type.
_NODE_ID_VALUE_KEYS: frozenset[str] = frozenset({"node", "node_id"})
_NEXT_KEY = "next"


def migrate_graph_checkpoint(value: object, *, normalize_next_tuples: bool = False) -> object:
    """Rewrite pre-rename LangGraph node ids in deserialized checkpoint payloads.

    Pure id remap: containers keep their type, so a nested ``next`` list stays a list.
    Node ids appear in the resume frontier (``next``), in task records (``node``) and in
    nested mappings, so the walk is recursive.

    ``normalize_next_tuples`` additionally restores LangGraph's ``next: tuple`` shape,
    which JSON/msgpack widen to a list on the way through the serializer. Only the
    checkpoint serializer sets it — it is the call site that owns the LangGraph contract.
    """
    if isinstance(value, dict):
        migrated: dict[Any, object] = {}
        for key, item in value.items():
            if key == _NEXT_KEY and isinstance(item, list | tuple):
                migrated[key] = _migrate_next(item, normalize_tuples=normalize_next_tuples)
            elif isinstance(key, str) and key in _NODE_ID_VALUE_KEYS and isinstance(item, str):
                migrated[key] = _remap_legacy_node_id(item)
            else:
                migrated[key] = migrate_graph_checkpoint(item, normalize_next_tuples=normalize_next_tuples)
        return migrated
    if isinstance(value, list):
        return [migrate_graph_checkpoint(item, normalize_next_tuples=normalize_next_tuples) for item in value]
    if isinstance(value, tuple):
        return tuple(migrate_graph_checkpoint(item, normalize_next_tuples=normalize_next_tuples) for item in value)
    return value


def _migrate_next(
    nodes: list[object] | tuple[object, ...],
    *,
    normalize_tuples: bool,
) -> tuple[str, ...] | list[str]:
    """Remap the resume frontier, keeping (or restoring) its container type."""
    remapped = [_remap_legacy_node_id(str(node)) for node in nodes]
    if normalize_tuples or isinstance(nodes, tuple):
        return tuple(remapped)
    return remapped


class MigratingJsonPlusSerializer(JsonPlusSerializer):
    """JsonPlusSerializer that remaps legacy node ids and restores the ``next`` tuple."""

    def loads_typed(self, data: tuple[str, bytes]) -> object:
        restored = super().loads_typed(data)
        return migrate_graph_checkpoint(restored, normalize_next_tuples=True)


def build_checkpoint_serde() -> SerializerProtocol:
    """JsonPlusSerializer with explicit allowlist (no silent unregistered types)."""
    return MigratingJsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_MSGPACK_ALLOWLIST)
