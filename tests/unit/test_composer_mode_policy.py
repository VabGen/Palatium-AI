"""ComposerModePolicy floors Intent axes without inventing task_kind (055)."""

from __future__ import annotations

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.policies.composer_mode import ComposerModePolicy
from palatium_ai.domain.policies.researcher_tier import ResearcherTierPolicy


def _intent(**kwargs: object) -> IntentClassifierOutput:
    base = {
        "task_kind": "knowledge_request",
        "requires_mcp": False,
        "candidate_capabilities": (),
        "grounding": "optional",
        "grounding_reason": "",
        "confidence": 0.9,
        "reasoning": "unit",
    }
    base.update(kwargs)
    return IntentClassifierOutput.model_validate(base)


def test_web_search_raises_grounding_required() -> None:
    out = ComposerModePolicy.apply(_intent(), "web_search")
    assert out is not None
    assert out.grounding == "required"
    assert out.task_kind == "knowledge_request"
    assert "web_search" in out.grounding_reason


def test_agent_sets_requires_mcp() -> None:
    out = ComposerModePolicy.apply(_intent(), "agent")
    assert out is not None
    assert out.requires_mcp is True
    assert out.grounding == "optional"


def test_deep_think_bumps_researcher_tier() -> None:
    out = ComposerModePolicy.apply(_intent(grounding="none"), "deep_think")
    assert out is not None
    assert out.grounding == "optional"
    decision = ResearcherTierPolicy.decide(strategy="reason_only", composer_mode="deep_think")
    assert decision.model_tier == "deep_reasoning"


def test_null_mode_is_noop() -> None:
    src = _intent(requires_mcp=True, grounding="required")
    assert ComposerModePolicy.apply(src, None) is src
