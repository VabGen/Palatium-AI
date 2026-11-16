# tests/unit/test_graph_web_mcp.py

"""graph_query / web_fallback MCP tools + Cypher safety."""

from __future__ import annotations

import json

import pytest

from palatium_ai.domain.graph.cypher_safety import (
    assert_graph_query_safe,
    assert_params_cover_refs,
    assert_read_only_cypher,
)
from palatium_ai.domain.graph.temporal import ACTIVE_FACT_AS_OF_PREDICATE
from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.web.stub_web_search_port import StubWebSearchPort


def test_cypher_rejects_write_clauses() -> None:
    with pytest.raises(ValueError, match="read-only"):
        assert_read_only_cypher("MATCH (n) DELETE n RETURN n")


def test_cypher_rejects_string_interpolation() -> None:
    with pytest.raises(ValueError, match="interpolation"):
        assert_read_only_cypher('MATCH (n) WHERE n.id = " + user_id + " RETURN n')


@pytest.mark.parametrize(
    "cypher",
    (
        "MATCH (n) WHERE n.id = %s RETURN n",
        'MATCH (n) WHERE n.id = f"{uid}" RETURN n',
        "MATCH (n {user_id}) RETURN n",  # f-string placeholder left in the text
        "MATCH (n {kind: 'fact'}) RETURN n",  # inlined literal instead of $param
        "MATCH (n {user_id: $user_id, kind: 'fact'}) RETURN n",  # mixed: literal still inlined
    ),
)
def test_cypher_rejects_values_embedded_in_query_text(cypher: str) -> None:
    """Rule 070: values must be bound, so any embedded value is refused."""
    with pytest.raises(ValueError, match="interpolation"):
        assert_read_only_cypher(cypher)


@pytest.mark.parametrize(
    "cypher",
    (
        "MATCH (f:Fact {user_id: $user_id}) RETURN f.text AS fact LIMIT $lim",
        "MATCH (n {}) RETURN n",
        "MATCH (n {user_id: $user_id, org_id: $org_id}) RETURN n",
    ),
)
def test_cypher_allows_property_maps_bound_to_params(cypher: str) -> None:
    """Regression: the property-map form is the canonical pattern, not interpolation."""
    assert_read_only_cypher(cypher)


def test_cypher_requires_bound_params() -> None:
    with pytest.raises(ValueError, match="missing Cypher params"):
        assert_params_cover_refs(
            "MATCH (d:Document) WHERE d.user_id = $uid RETURN d LIMIT $lim",
            {"uid": "u1"},
        )


def test_graph_query_requires_tenant_scope() -> None:
    """070: an unscoped read must be rejected before it reaches the driver (cross-tenant leak)."""
    with pytest.raises(ValueError, match="tenant"):
        assert_graph_query_safe("MATCH (n) RETURN n", {"user_id": "u1"})


@pytest.mark.parametrize(
    "cypher",
    (
        "MATCH (f:MemoryFact) WHERE f.user_id = $user_id RETURN f.text AS text",
        "MATCH (f:`MemoryFact` {user_id: $user_id}) RETURN f.text AS text",
        "MATCH (f:MemoryFact) WHERE f.user_id = $user_id RETURN f.valid_at AS at",
    ),
)
def test_graph_query_rejects_fact_reads_without_as_of(cypher: str) -> None:
    """M5 audit F1: fail-open bi-temporal read would return superseded/expired facts."""
    with pytest.raises(ValueError, match="as_of"):
        assert_graph_query_safe(cypher, {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"})


def test_graph_query_allows_fact_read_with_as_of_predicate() -> None:
    cypher = f"MATCH (f:MemoryFact) WHERE {ACTIVE_FACT_AS_OF_PREDICATE} RETURN f.text AS text"
    assert_graph_query_safe(cypher, {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"})


def test_graph_query_accepts_the_predicate_under_any_alias() -> None:
    """F1b: the guard is about the filter, not the letter ``f`` the constant happens to use."""
    predicate = ACTIVE_FACT_AS_OF_PREDICATE.replace("f.", "fact.")
    cypher = f"MATCH (fact:MemoryFact) WHERE {predicate} RETURN fact.text AS text"
    assert_graph_query_safe(cypher, {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"})


@pytest.mark.parametrize(
    "cypher",
    (
        # References the parameter and filters nothing — the exact F1b gap.
        "MATCH (f:MemoryFact) WHERE f.user_id = $user_id AND $as_of IS NOT NULL RETURN f.text AS text",
        # Only valid-time: system-time (forget) would leak expired facts.
        (
            "MATCH (f:MemoryFact) WHERE f.user_id = $user_id "
            "AND (f.valid_at IS NULL OR f.valid_at <= datetime($as_of)) "
            "AND (f.invalid_at IS NULL OR f.invalid_at > datetime($as_of)) "
            "RETURN f.text AS text"
        ),
        # No null guards: `NULL <= x` is NULL, so open-ended facts silently disappear.
        (
            "MATCH (f:MemoryFact) WHERE f.user_id = $user_id "
            "AND datetime($as_of) >= f.valid_at AND datetime($as_of) < f.invalid_at "
            "RETURN f.text AS text"
        ),
    ),
)
def test_graph_query_rejects_partial_temporal_predicates(cypher: str) -> None:
    """F1b: binding ``$as_of`` is not the same as filtering on it."""
    with pytest.raises(ValueError, match="bi-temporal predicate"):
        assert_graph_query_safe(cypher, {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"})


def test_graph_query_rejects_anonymous_fact_node() -> None:
    """Without an alias the predicate cannot be checked, so the shape is refused outright."""
    with pytest.raises(ValueError, match="alias"):
        assert_graph_query_safe(
            "MATCH (:MemoryFact {user_id: $user_id}) RETURN count(*) AS n",
            {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"},
        )


def test_graph_query_requires_the_predicate_on_every_fact_alias() -> None:
    """Two fact nodes (e.g. a contradiction pair) cannot leave one of them unfiltered."""
    cypher = (
        "MATCH (old:MemoryFact), (new:MemoryFact) WHERE "
        + ACTIVE_FACT_AS_OF_PREDICATE
        + " AND old.user_id = new.user_id RETURN old.text AS before, new.text AS after"
    )
    with pytest.raises(ValueError, match=r"new\.valid_at"):
        assert_graph_query_safe(cypher, {"user_id": "u1", "as_of": "2026-10-20T00:00:00Z"})


def test_graph_query_leaves_non_fact_labels_alone() -> None:
    """The temporal rule is specific to MemoryFact, not a blanket ``$as_of`` requirement."""
    assert_graph_query_safe(
        "MATCH (d:Document {user_id: $user_id}) RETURN d.title AS title",
        {"user_id": "u1"},
    )


@pytest.mark.asyncio()
async def test_graph_query_handler_rejects_fact_read_without_as_of() -> None:
    """The guard reaches the agent as a structured error, not silent stale rows."""
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=InMemoryGraphPort(),
    )

    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-1",
            "cypher": "MATCH (f:MemoryFact) WHERE f.user_id = $user_id RETURN f.text AS text",
            "params_json": json.dumps({"user_id": "user-1"}),
        },
    )

    assert result.is_error is True
    assert "as_of" in result.content[0]["text"]


@pytest.mark.asyncio()
async def test_graph_query_handler_returns_row() -> None:
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=InMemoryGraphPort(),
    )

    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-1",
            "cypher": "MATCH (d:Document) WHERE d.user_id = $user_id RETURN d LIMIT $lim",
            "params_json": json.dumps({"user_id": "user-1", "lim": 5}),
        },
    )

    assert result.is_error is False

    payload = json.loads(result.content[0]["text"])

    assert payload["row_count"] == 1
    assert payload["rows"][0]["user_id"] == "user-1"


@pytest.mark.asyncio()
async def test_graph_query_handler_rejects_unscoped_cypher() -> None:
    """070: handler must surface tenant-scope violations as a structured MCP error, not rows."""
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=InMemoryGraphPort(),
    )

    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-1",
            "cypher": "MATCH (n) RETURN n LIMIT $lim",
            "params_json": json.dumps({"lim": 5}),
        },
    )

    assert result.is_error is True
    assert "tenant" in result.content[0]["text"]


@pytest.mark.asyncio()
async def test_graph_query_overwrites_params_user_id() -> None:
    """Defense-in-depth: params_json.user_id must not stick to a foreign tenant."""

    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=InMemoryGraphPort(),
    )

    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-actor",
            "cypher": "MATCH (d:Document) WHERE d.user_id = $user_id RETURN d LIMIT $lim",
            "params_json": json.dumps({"user_id": "user-victim", "lim": 5}),
        },
    )

    assert result.is_error is False

    payload = json.loads(result.content[0]["text"])

    assert payload["rows"][0]["user_id"] == "user-actor"


@pytest.mark.asyncio()
async def test_graph_query_rejects_merge() -> None:
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=InMemoryGraphPort(),
    )

    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-1",
            "cypher": "MERGE (n:Doc {id: $id}) RETURN n",
            "params_json": json.dumps({"id": "x"}),
        },
    )

    assert result.is_error is True


@pytest.mark.asyncio()
async def test_web_fallback_tags_source() -> None:
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        web_search_port=StubWebSearchPort(),
    )

    result = await handler.call_tool(
        "web_fallback",
        {"user_id": "user-1", "query": "Palatium architecture", "max_results": "3"},
    )

    assert result.is_error is False

    payload = json.loads(result.content[0]["text"])

    assert payload["source"] == "web"
    assert payload["reliability"] == "external_unverified"
    assert payload["provider"] == "stub"
