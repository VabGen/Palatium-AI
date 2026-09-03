"""MemoryNamespacePolicy — bind scope_id to authenticated principal."""

from __future__ import annotations

import json

import pytest

from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy


def test_bind_user_scope_defaults_to_owner() -> None:
    binding = MemoryNamespacePolicy.bind_scope(
        namespace_kind="user",
        requested_scope_id="",
        owner_user_id="user-a",
        org_id="org-1",
        thread_id="thread-1",
    )
    assert binding.scope_id == "user-a"


def test_bind_user_scope_rejects_foreign_scope() -> None:
    with pytest.raises(ValueError, match="authenticated user"):
        MemoryNamespacePolicy.bind_scope(
            namespace_kind="user",
            requested_scope_id="user-victim",
            owner_user_id="user-a",
            org_id="org-1",
            thread_id="thread-1",
        )


def test_bind_thread_scope_rejects_foreign_thread() -> None:
    with pytest.raises(ValueError, match="thread_id"):
        MemoryNamespacePolicy.bind_scope(
            namespace_kind="thread",
            requested_scope_id="thread-other",
            owner_user_id="user-a",
            org_id="org-1",
            thread_id="thread-1",
        )


def test_bind_org_requires_claim_and_match() -> None:
    with pytest.raises(ValueError, match="org_id"):
        MemoryNamespacePolicy.bind_scope(
            namespace_kind="org",
            requested_scope_id="",
            owner_user_id="user-a",
            org_id=None,
            thread_id="thread-1",
        )
    with pytest.raises(ValueError, match="authenticated org"):
        MemoryNamespacePolicy.bind_scope(
            namespace_kind="org",
            requested_scope_id="org-other",
            owner_user_id="user-a",
            org_id="org-1",
            thread_id="thread-1",
        )
    binding = MemoryNamespacePolicy.bind_scope(
        namespace_kind="org",
        requested_scope_id="org-1",
        owner_user_id="user-a",
        org_id="org-1",
        thread_id="thread-1",
    )
    assert binding.scope_id == "org-1"


def test_mcp_user_scope_consistency() -> None:
    assert MemoryNamespacePolicy.mcp_user_scope_consistent(namespace_kind="user", scope_id="u1", user_id="u1")
    assert not MemoryNamespacePolicy.mcp_user_scope_consistent(namespace_kind="user", scope_id="victim", user_id="u1")
    assert MemoryNamespacePolicy.mcp_user_scope_consistent(namespace_kind="thread", scope_id="t1", user_id="u1")


def test_mcp_org_scope_consistency() -> None:
    assert MemoryNamespacePolicy.mcp_org_scope_consistent(namespace_kind="org", scope_id="org-1", org_id="org-1")
    assert not MemoryNamespacePolicy.mcp_org_scope_consistent(
        namespace_kind="org", scope_id="org-1", org_id="org-other"
    )
    assert not MemoryNamespacePolicy.mcp_org_scope_consistent(namespace_kind="org", scope_id="org-1", org_id=None)
    assert MemoryNamespacePolicy.mcp_org_scope_consistent(namespace_kind="user", scope_id="u1", org_id=None)


def test_bind_mcp_memory_arguments_forces_actor_org() -> None:
    bound = MemoryNamespacePolicy.bind_mcp_memory_arguments(
        tool_name="save_memory",
        arguments={
            "user_id": "attacker",
            "namespace_kind": "org",
            "scope_id": "org-victim",
            "org_id": "org-victim",
            "entry_key": "x",
            "value_json": "{}",
        },
        actor_user_id="attacker",
        actor_org_id="org-attacker",
    )
    assert bound["scope_id"] == "org-attacker"
    assert bound["org_id"] == "org-attacker"
    assert bound["user_id"] == "attacker"


def test_bind_mcp_memory_arguments_requires_actor_for_org() -> None:
    with pytest.raises(ValueError, match="actor_org_id"):
        MemoryNamespacePolicy.bind_mcp_memory_arguments(
            tool_name="save_memory",
            arguments={"namespace_kind": "org", "scope_id": "org-x"},
            actor_org_id="",
        )


def test_bind_mcp_consolidate_forces_user_and_strips_unowned_org() -> None:
    bound = MemoryNamespacePolicy.bind_mcp_memory_arguments(
        tool_name="consolidate_memory",
        arguments={
            "user_id": "victim",
            "thread_id": "thread-victim",
            "org_id": "org-victim",
        },
        actor_user_id="attacker",
        actor_thread_id="thread-attacker",
        actor_org_id="",
    )
    assert bound["user_id"] == "attacker"
    assert bound["thread_id"] == "thread-attacker"
    assert "org_id" not in bound


def test_bind_mcp_consolidate_requires_actor_user() -> None:
    with pytest.raises(ValueError, match="actor_user_id"):
        MemoryNamespacePolicy.bind_mcp_memory_arguments(
            tool_name="consolidate_memory",
            arguments={"user_id": "u1", "thread_id": "t1"},
            actor_user_id="",
        )


def test_bind_mcp_search_memory_forces_user_and_org() -> None:
    bound = MemoryNamespacePolicy.bind_mcp_memory_arguments(
        tool_name="search_memory",
        arguments={
            "user_id": "victim",
            "query": "x",
            "thread_id": "thread-victim",
            "org_id": "org-victim",
        },
        actor_user_id="user-a",
        actor_org_id="org-a",
        actor_thread_id="thread-a",
    )
    assert bound["user_id"] == "user-a"
    assert bound["org_id"] == "org-a"
    assert bound["thread_id"] == "thread-a"


def test_bind_mcp_graph_query_overwrites_params_user_id() -> None:
    bound = MemoryNamespacePolicy.bind_mcp_memory_arguments(
        tool_name="graph_query",
        arguments={
            "user_id": "victim",
            "cypher": "MATCH (n) WHERE n.user_id = $user_id RETURN n",
            "params_json": '{"user_id": "victim", "lim": 1}',
        },
        actor_user_id="user-a",
    )
    assert bound["user_id"] == "user-a"
    params = json.loads(str(bound["params_json"]))
    assert params["user_id"] == "user-a"
    assert params["lim"] == 1
