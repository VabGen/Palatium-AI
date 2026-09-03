"""ContextualizerPolicy — LLM rewrite only for prior-dependent task kinds."""

from palatium_ai.domain.policies import ContextualizerPolicy


def test_skip_without_assistant_prior() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=False,
        task_kind="knowledge_request",
        requires_mcp=False,
    )
    assert decision.invoke_llm is False


def test_skip_social_even_with_prior() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=True,
        task_kind="social_conversation",
        requires_mcp=False,
    )
    assert decision.invoke_llm is False


def test_skip_capability_discovery_with_prior() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=True,
        task_kind="capability_discovery",
        requires_mcp=False,
    )
    assert decision.invoke_llm is False


def test_invoke_for_knowledge_with_prior() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=True,
        task_kind="knowledge_request",
        requires_mcp=False,
    )
    assert decision.invoke_llm is True


def test_invoke_when_requires_mcp() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=True,
        task_kind="social_conversation",
        requires_mcp=True,
    )
    assert decision.invoke_llm is True


def test_invoke_unknown_task_kind_with_prior() -> None:
    decision = ContextualizerPolicy.decide(
        has_assistant_prior=True,
        task_kind=None,
        requires_mcp=False,
    )
    assert decision.invoke_llm is True
