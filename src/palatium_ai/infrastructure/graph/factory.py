# src/palatium_ai/infrastructure/graph/factory.py

"""GraphPort / GraphWritePort factory — shared Neo4j transport when enabled (070 / 060)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.graph.port import GraphPort
from palatium_ai.domain.graph.write_port import GraphWritePort
from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


@dataclass(frozen=True, slots=True)
class GraphPorts:
    """Paired read + write ports; one shared Neo4j driver when backend=neo4j."""

    query: GraphPort
    write: GraphWritePort
    _shared_closer: object | None = None

    async def aclose(self) -> None:
        """Close shared transport once (idempotent)."""
        closer = self._shared_closer
        if closer is None:
            for port in (self.query, self.write):
                aclose = getattr(port, "aclose", None)
                if aclose is not None:
                    await aclose()
            return
        aclose = getattr(closer, "aclose", None)
        if aclose is not None:
            await aclose()


def build_graph_ports(settings: Settings) -> GraphPorts:
    """Build query + write ports; share one Neo4j driver when configured."""
    backend = settings.memory.graph_query_backend
    if backend != "neo4j":
        return GraphPorts(query=InMemoryGraphPort(), write=InMemoryGraphWritePort())

    password = _neo4j_password(settings)
    if not password.strip():
        logger.warning("GRAPH_QUERY_BACKEND=neo4j but GRAPHITI_NEO4J_PASSWORD unset; using in-memory graph ports")
        return GraphPorts(query=InMemoryGraphPort(), write=InMemoryGraphWritePort())

    try:
        from palatium_ai.infrastructure.graph.neo4j_graph_port import Neo4jDriverTransport, Neo4jGraphPort
        from palatium_ai.infrastructure.graph.neo4j_graph_write_port import Neo4jGraphWritePort

        transport = Neo4jDriverTransport(
            uri=settings.memory.graphiti_neo4j_uri,
            user=settings.memory.graphiti_neo4j_user,
            password=password,
        )
        logger.info("GraphPorts: Neo4j (shared driver)", uri=settings.memory.graphiti_neo4j_uri)
        return GraphPorts(
            query=Neo4jGraphPort(transport),
            write=Neo4jGraphWritePort(transport),
            _shared_closer=transport,
        )
    except (ImportError, ValueError) as exc:
        logger.warning("Neo4j graph ports unavailable; using in-memory stubs", error=str(exc))
        return GraphPorts(query=InMemoryGraphPort(), write=InMemoryGraphWritePort())


def build_graph_port(settings: Settings) -> GraphPort:
    """Select GraphPort backend (compat wrapper around ``build_graph_ports``)."""
    return build_graph_ports(settings).query


def build_graph_write_port(settings: Settings) -> GraphWritePort:
    """Select GraphWritePort for promote (compat wrapper; prefer ``build_graph_ports``)."""
    return build_graph_ports(settings).write


def _neo4j_password(settings: Settings) -> str:
    if settings.memory.graphiti_neo4j_password is None:
        return ""
    return settings.memory.graphiti_neo4j_password.get_secret_value()
