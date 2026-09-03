# src/palatium_ai/domain/graph/types.py

"""Graph query contracts (Neo4j / Cognee long-term knowledge, 060/070)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GraphQueryCommand(BaseModel):
    """Parameterized read-only Cypher invocation."""

    model_config = {"frozen": True}

    user_id: str = Field(min_length=1, max_length=128)
    cypher: str = Field(min_length=1, max_length=8_000)
    params: dict[str, object] = Field(default_factory=dict)
    limit: int = Field(default=25, ge=1, le=100)


class GraphQueryRow(BaseModel):
    """One result row as a flat string map (serializable for MCP)."""

    model_config = {"frozen": True}

    values: dict[str, str] = Field(default_factory=dict)


class GraphQueryResult(BaseModel):
    """Rows returned by ``graph_query``."""

    model_config = {"frozen": True}

    rows: tuple[GraphQueryRow, ...] = ()
    row_count: int = Field(ge=0, default=0)
