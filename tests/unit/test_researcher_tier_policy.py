"""ResearcherTierPolicy — reason_only uses small; retrieval stays mid."""

from palatium_ai.application.agents.researcher.config import RESEARCHER_CONFIG, researcher_llm_config
from palatium_ai.domain.policies import ResearcherTierPolicy


def test_reason_only_uses_small() -> None:
    decision = ResearcherTierPolicy.decide(strategy="reason_only")
    assert decision.model_tier == "small"
    assert decision.reason == "strategy:reason_only"


def test_retrieve_keeps_mid() -> None:
    decision = ResearcherTierPolicy.decide(strategy="retrieve_then_reason")
    assert decision.model_tier == "mid"


def test_researcher_llm_config_copies_for_reason_only() -> None:
    cfg = researcher_llm_config(RESEARCHER_CONFIG, strategy="reason_only")
    assert cfg.model_tier == "small"
    assert RESEARCHER_CONFIG.model_tier == "mid"
    assert researcher_llm_config(RESEARCHER_CONFIG, strategy="direct_tool_call") is RESEARCHER_CONFIG
