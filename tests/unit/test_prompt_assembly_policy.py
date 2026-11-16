# tests/unit/test_prompt_assembly_policy.py

"""CMD2 PromptAssemblyPolicy tier order + cache invariants."""

from __future__ import annotations

import pytest

from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.prompt_assembly import (
    PromptAssemblyParts,
    PromptAssemblyPolicy,
)


def test_assemble_order_stable_context_volatile() -> None:
    assembled = PromptAssemblyPolicy.assemble(
        PromptAssemblyParts(
            system_identity="You are the researcher.",
            project_agents_md="Prefer HITL for writes.",
            tool_guidance="search_memory: read",
            thread_meta="thread_id=t1",
            skill_catalog="- memory-os-write: gated writes",
            memory_block="- prefers duck (verified)",
            dialog_block="user: hi\nassistant: hello",
            timestamp="2026-11-03T00:00:00Z",
            user_content='{"user_text":"what next?"}',
        )
    )
    PromptAssemblyPolicy.assert_tier_invariants(assembled)
    assert assembled.tier_order[0] == "stable"
    assert "context" in assembled.tier_order
    assert assembled.tier_order[-1] == "volatile"
    assert assembled.messages[0].cache_control == "ephemeral"
    assert "Prefer HITL" in assembled.messages[0].content
    assert assembled.messages[0].content.index("You are the researcher") < assembled.messages[0].content.index("Prefer HITL")
    context_msg = next(m for m, t in zip(assembled.messages, assembled.tier_order, strict=True) if t == "context")
    assert "prefers duck" in context_msg.content
    assert "memory-os-write" in context_msg.content
    assert context_msg.cache_control is None
    volatile_systems = [
        m for m, t in zip(assembled.messages, assembled.tier_order, strict=True) if t == "volatile" and m.role == "system"
    ]
    assert volatile_systems
    assert "user: hi" in volatile_systems[0].content
    assert assembled.messages[-1].role == "user"
    assert "what next?" in assembled.messages[-1].content


def test_assemble_omits_empty_tiers() -> None:
    assembled = PromptAssemblyPolicy.assemble(
        PromptAssemblyParts(
            system_identity="Identity only.",
            user_content="ask",
        )
    )
    PromptAssemblyPolicy.assert_tier_invariants(assembled)
    assert assembled.tier_order == ("stable", "volatile")
    assert len(assembled.messages) == 2


def test_tiers_do_not_mix_memory_into_stable() -> None:
    assembled = PromptAssemblyPolicy.assemble(
        PromptAssemblyParts(
            system_identity="Stable identity.",
            memory_block="SECRET_FACT_SHOULD_NOT_BE_STABLE",
            user_content="q",
        )
    )
    assert "SECRET_FACT_SHOULD_NOT_BE_STABLE" not in assembled.messages[0].content
    assert any("SECRET_FACT_SHOULD_NOT_BE_STABLE" in m.content for m in assembled.messages[1:])


def test_apply_cache_hints_idempotent_and_legacy() -> None:
    legacy = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="u"),
    ]
    marked = PromptAssemblyPolicy.apply_cache_hints(legacy)
    assert marked[0].cache_control == "ephemeral"
    again = PromptAssemblyPolicy.apply_cache_hints(marked)
    assert again[0].cache_control == "ephemeral"
    assert again[1].cache_control is None


def test_assert_rejects_cache_on_non_stable() -> None:
    bad = PromptAssemblyPolicy.assemble(PromptAssemblyParts(system_identity="id", memory_block="m", user_content="u"))
    poisoned = list(bad.messages)
    poisoned[1] = poisoned[1].model_copy(update={"cache_control": "ephemeral"})
    with pytest.raises(AssertionError, match="cache_control"):
        PromptAssemblyPolicy.assert_tier_invariants(bad.model_copy(update={"messages": tuple(poisoned)}))
