"""FormatterFastPathPolicy — presentation LLM always (055)."""

from __future__ import annotations

from palatium_ai.domain.policies import FormatterFastPathPolicy


def test_presentation_always_invokes_llm() -> None:
    decision = FormatterFastPathPolicy.decide(source_content="Prior answer ready to show.")
    assert decision.skip_llm is False
    assert decision.reason == "presentation_requires_formatter_llm"


def test_empty_source_still_invokes_llm() -> None:
    decision = FormatterFastPathPolicy.decide(source_content="  ")
    assert decision.skip_llm is False
    assert decision.reason == "presentation_requires_formatter_llm"


def test_user_choice_still_invokes_llm() -> None:
    decision = FormatterFastPathPolicy.decide(
        source_content="Pick one layout.",
        requires_user_choice=True,
    )
    assert decision.skip_llm is False
    assert decision.reason == "requires_user_choice"
