# src/palatium_ai/infrastructure/graph/factory.py

"""GraphPort factory — in-memory stub vs Neo4j driver (070)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.graph.port import GraphPort
from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


def build_graph_port(settings: Settings) -> GraphPort:
    """Select GraphPort backend from settings; fail open to in-memory when misconfigured."""
    backend = settings.memory.graph_query_backend
    if backend != "neo4j":
        return InMemoryGraphPort()

    password = (
        settings.memory.graphiti_neo4j_password.get_secret_value()
        if settings.memory.graphiti_neo4j_password is not None
        else ""
    )
    if not password.strip():
        logger.warning("GRAPH_QUERY_BACKEND=neo4j but GRAPHITI_NEO4J_PASSWORD unset; using in-memory graph port")
        return InMemoryGraphPort()

    try:
        from palatium_ai.infrastructure.graph.neo4j_graph_port import Neo4jDriverTransport, Neo4jGraphPort

        transport = Neo4jDriverTransport(
            uri=settings.memory.graphiti_neo4j_uri,
            user=settings.memory.graphiti_neo4j_user,
            password=password,
        )
        logger.info("GraphPort: Neo4j", uri=settings.memory.graphiti_neo4j_uri)
        return Neo4jGraphPort(transport)
    except (ImportError, ValueError) as exc:
        logger.warning("Neo4j graph port unavailable; using in-memory stub", error=str(exc))
        return InMemoryGraphPort()
