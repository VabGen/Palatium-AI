"""OptionSynthesizer locale pinning (055): English must not leak into a ru turn.

Regression for the post-Formatter HITL path: synthesized framing/labels are
user-facing and must follow ``response_locale``, not the prompt's own language.
"""

from __future__ import annotations

import pytest

from palatium_ai.application.services.option_synthesizer import OptionSynthesizer
from tests.conftest import FakeLLMPort, SequentialFakeLLMPort

_ENGLISH = (
    '{"framing":"Here is a curated list of absurd anecdote topics:",'
    '"options":[{"action_id":"choice_1","label":"Talking animals"},'
    '{"action_id":"choice_2","label":"Broken logic"}]}'
)
_RUSSIAN = (
    '{"framing":"Выберите тему анекдота:",'
    '"options":[{"action_id":"choice_1","label":"Говорящие животные"},'
    '{"action_id":"choice_2","label":"Сломанная логика"}]}'
)


@pytest.mark.asyncio
async def test_keeps_matching_locale_without_repair() -> None:
    llm = FakeLLMPort(_RUSSIAN)
    synth = OptionSynthesizer(llm)

    result = await synth.synthesize(user_text="предложи темы", response_locale="ru-RU")

    assert result.framing == "Выберите тему анекдота:"
    assert [action.label for action in result.actions] == [
        "Говорящие животные",
        "Сломанная логика",
    ]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_repairs_english_output_for_russian_turn() -> None:
    llm = SequentialFakeLLMPort([_ENGLISH, _RUSSIAN])
    synth = OptionSynthesizer(llm)

    result = await synth.synthesize(user_text="предложи темы", response_locale="ru-RU")

    assert result.framing == "Выберите тему анекдота:"
    assert [action.label for action in result.actions] == [
        "Говорящие животные",
        "Сломанная логика",
    ]
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_drops_synthesis_when_repair_stays_english() -> None:
    llm = SequentialFakeLLMPort([_ENGLISH, _ENGLISH])
    synth = OptionSynthesizer(llm)

    result = await synth.synthesize(user_text="предложи темы", response_locale="ru-RU")

    assert result.actions == ()
    assert result.framing is None
