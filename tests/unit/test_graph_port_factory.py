"""Unit tests for GraphPort factory."""

from __future__ import annotations

from palatium_ai.core.config.settings import Settings
from palatium_ai.infrastructure.graph.factory import build_graph_port
from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort


def test_build_graph_port_defaults_to_in_memory() -> None:
    settings = Settings()
    port = build_graph_port(settings)
    assert isinstance(port, InMemoryGraphPort)
