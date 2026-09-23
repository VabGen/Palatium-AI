"""Unit tests for GraphPort / GraphWritePort factory (shared driver)."""

from __future__ import annotations

from palatium_ai.core.config.settings import Settings
from palatium_ai.infrastructure.graph.factory import build_graph_port, build_graph_ports, build_graph_write_port
from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort


def test_build_graph_port_defaults_to_in_memory() -> None:
    settings = Settings()
    port = build_graph_port(settings)
    assert isinstance(port, InMemoryGraphPort)


def test_build_graph_ports_pairs_in_memory() -> None:
    settings = Settings()
    ports = build_graph_ports(settings)
    assert isinstance(ports.query, InMemoryGraphPort)
    assert isinstance(ports.write, InMemoryGraphWritePort)
    assert ports._shared_closer is None


def test_build_graph_write_port_defaults_to_in_memory() -> None:
    settings = Settings()
    assert isinstance(build_graph_write_port(settings), InMemoryGraphWritePort)
