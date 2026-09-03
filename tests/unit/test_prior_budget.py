"""Worker prior budget: trusted user documents must not use chat-excerpt clip."""

from __future__ import annotations

from typing import cast

from palatium_ai.application.orchestration.selectors import resolved_prior_assistant_content
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.policies import EffectiveRoutingIntent


def test_trusted_prior_uses_worker_summary_budget() -> None:
    doc = "D" * 5_000
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "analyze this",
            "prompt_budget": MemoryPromptBudget(
                prior_excerpt_max_chars=1_500,
                worker_summary_max_chars=8_000,
            ),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                prior_context=doc,
                trust_prior_for_workers=True,
                reasoning="answer follow-up with user payload",
            ),
        },
    )
    out = resolved_prior_assistant_content(state)
    assert out is not None
    assert len(out) > 1_500
    assert "D" * 4_000 in out


def test_untrusted_prior_keeps_excerpt_budget() -> None:
    doc = "D" * 5_000
    state = cast(
        "AgentGraphState",
        {
            "task_id": "t1",
            "user_text": "hi",
            "prompt_budget": MemoryPromptBudget(
                prior_excerpt_max_chars=1_500,
                worker_summary_max_chars=8_000,
            ),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="social_conversation",
                prior_context=doc,
                trust_prior_for_workers=False,
                reasoning="phatic",
            ),
        },
    )
    out = resolved_prior_assistant_content(state)
    assert out is not None
    assert len(out) <= 1_600
