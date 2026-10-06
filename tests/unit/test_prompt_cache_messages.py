"""Unit: harness marks leading system message for prompt cache (P0.3)."""

from __future__ import annotations

from palatium_ai.application.agents.harness import _with_system_prompt_cache
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.infrastructure.llm.litellm_adapter import _to_litellm_messages


def test_with_system_prompt_cache_marks_first_system() -> None:
    messages = [
        ChatMessage(role="system", content="STATIC"),
        ChatMessage(role="user", content="hi"),
    ]
    out = _with_system_prompt_cache(messages)
    assert out[0].cache_control == "ephemeral"
    assert out[1].cache_control is None


def test_to_litellm_messages_emits_cache_control_block() -> None:
    messages = [
        ChatMessage(role="system", content="STATIC", cache_control="ephemeral"),
        ChatMessage(role="user", content="hi"),
    ]
    payload = _to_litellm_messages(messages)
    assert isinstance(payload[0]["content"], list)
    block = payload[0]["content"][0]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert payload[1]["content"] == "hi"
