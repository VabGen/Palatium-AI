# tests/unit/test_assistant_identity.py

"""One product identity for every writer that produces user-facing text (055, 020).

Motivating leak: "как тебя зовут" and "что ты умеешь" were answered by the writer's own
role prompt — "Меня зовут Formatter", "Я — исследователь (Researcher)". Identity is a
product fact, not a property of the pipeline stage that happened to compose the answer.
"""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.analyst.prompts import ANALYST_SYSTEM_PROMPT
from palatium_ai.application.agents.coder.prompts import CODER_SYSTEM_PROMPT
from palatium_ai.application.agents.formatter.prompts import (
    FORMATTER_SCHEMA_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
)
from palatium_ai.application.agents.researcher.prompts import RESEARCHER_SYSTEM_PROMPT
from palatium_ai.domain.policies.assistant_identity import (
    ASSISTANT_NAME,
    IDENTITY_CAPABILITIES,
    IDENTITY_CORE,
    agent_role_labels,
)

_USER_FACING_WRITERS = (
    FORMATTER_SYSTEM_PROMPT,
    FORMATTER_SCHEMA_PROMPT,
    RESEARCHER_SYSTEM_PROMPT,
    ANALYST_SYSTEM_PROMPT,
    CODER_SYSTEM_PROMPT,
)


def test_identity_core_names_the_product_and_speaks_as_one_assistant() -> None:
    assert ASSISTANT_NAME in IDENTITY_CORE
    assert "pipeline component" in IDENTITY_CORE
    assert "response_locale" in IDENTITY_CORE
    assert "never invent a" in IDENTITY_CORE.lower()


def test_capabilities_are_user_domain_facts_not_the_agent_registry() -> None:
    assert "EDMS" in IDENTITY_CAPABILITIES
    for label in agent_role_labels():
        assert label not in IDENTITY_CAPABILITIES


@pytest.mark.parametrize("prompt", _USER_FACING_WRITERS)
def test_every_writer_carries_the_identity_contract(prompt: str) -> None:
    assert prompt.startswith(IDENTITY_CORE)


@pytest.mark.parametrize("prompt", (RESEARCHER_SYSTEM_PROMPT, ANALYST_SYSTEM_PROMPT))
def test_answer_writers_can_ground_capability_asks(prompt: str) -> None:
    assert IDENTITY_CAPABILITIES in prompt


@pytest.mark.parametrize("prompt", _USER_FACING_WRITERS)
def test_no_writer_introduces_itself_by_internal_role(prompt: str) -> None:
    for stale_opening in (
        "You are the Formatter",
        "You are a Researcher worker",
        "You are the Analyst worker",
        "You are the Coder worker",
    ):
        assert stale_opening not in prompt


def test_role_labels_derive_from_the_registry_without_duplicates() -> None:
    labels = agent_role_labels()

    assert "Formatter" in labels
    assert "Researcher" in labels
    assert len(set(labels)) == len(labels)
