"""FormatterFastPathPolicy — presentation LLM always (055)."""

from __future__ import annotations

from palatium_ai.domain.policies import FormatterFastPathPolicy
from palatium_ai.domain.policies.formatter_fast_path import FormatterPassthroughSignals


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


def _plain_signals(*, shape_requested: bool) -> FormatterPassthroughSignals:
    return FormatterPassthroughSignals(
        source_chars=20,
        worker_confident=True,
        source_is_plain_prose=True,
        locale_matches=True,
        shape_requested=shape_requested,
    )


def test_plain_prose_may_pass_through_without_shape_request() -> None:
    decision = FormatterFastPathPolicy.decide(
        source_content="Короткий ответ.",
        passthrough=_plain_signals(shape_requested=False),
        passthrough_max_chars=200,
    )
    assert decision.skip_llm is True
    assert decision.reason == "passthrough_plain_prose"


def test_explicit_shape_requires_formatter_llm() -> None:
    decision = FormatterFastPathPolicy.decide(
        source_content="Короткий ответ.",
        passthrough=_plain_signals(shape_requested=True),
        passthrough_max_chars=200,
    )
    assert decision.skip_llm is False
    assert decision.reason == "shape_requested"
