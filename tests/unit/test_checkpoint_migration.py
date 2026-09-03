# tests/unit/test_checkpoint_migration.py

"""Checkpoint serde migrates legacy LangGraph node ids on load."""

from __future__ import annotations

from palatium_ai.core.types.graph_nodes import (
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
)
from palatium_ai.infrastructure.memory.checkpoint_serde import migrate_graph_checkpoint


def test_migrate_legacy_next_tuple() -> None:
    payload = {"next": ("contextualizer", "intent_classifier")}
    migrated = migrate_graph_checkpoint(payload)
    assert migrated == {"next": (NODE_CONTEXT_ENRICHER_CONTINUATION, "intent_classifier")}


def test_migrate_legacy_next_list_nested() -> None:
    payload = {"channel": {"next": ["context_weaver", "critic"]}}
    migrated = migrate_graph_checkpoint(payload)
    assert migrated == {"channel": {"next": [NODE_CONTEXT_ENRICHER_WEAVING, "critic"]}}


def test_migrate_passthrough_unknown_nodes() -> None:
    payload = {"next": ("researcher",)}
    assert migrate_graph_checkpoint(payload) == payload
