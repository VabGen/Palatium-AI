"""LiteLLM→Anthropic dials smoke: effort lands; verbosity is a silent drop.

Contract under test (provider incompatibility, not resolve logic):
1. ``reasoning_effort="high"`` reaches Anthropic as ``output_config.effort == "high"``.
2. ``verbosity="low"`` must **not** raise ``UnsupportedParamsError`` and must be
   absent from the Anthropic JSON body (adapter capability drop).
3. Call still completes (HTTP stub returns a valid message).

Goes through ``LiteLLMAdapter.generate`` + real LiteLLM Anthropic transformation.
HTTP is stubbed at ``AsyncHTTPHandler.post`` (no Anthropic key in CI).

Run with the rest of ``tests/integration`` (marker ``integration``).
"""

from __future__ import annotations

import json

from typing import Any

import pytest

from httpx import Request, Response
from pydantic import SecretStr

from palatium_ai.core.config.llm.anthropic import AnthropicLLMConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

pytestmark = [
    pytest.mark.integration(),
    pytest.mark.asyncio(),
    # LiteLLM→pydantic TypedDict ReadOnly warning; filterwarnings=error would fail first.
    pytest.mark.filterwarnings(
        "ignore:Item 'summary' on TypedDict class 'ChatCompletionReasoningItem':UserWarning",
    ),
]

_MODEL = "claude-opus-4-6"
_ANTHROPIC_BODY = {
    "id": "msg_smoke",
    "type": "message",
    "role": "assistant",
    "model": _MODEL,
    "content": [{"type": "text", "text": "pong"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 3, "output_tokens": 1},
}


@pytest.fixture()
def anthropic_request_capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub Anthropic HTTP; return the JSON body LiteLLM would POST."""
    captured: dict[str, Any] = {}

    async def _fake_post(self: object, url: object, *args: object, **kwargs: object) -> Response:
        _ = self, args
        captured["url"] = str(url)
        captured["json"] = kwargs.get("json")
        return Response(200, json=_ANTHROPIC_BODY, request=Request("POST", str(url)))

    monkeypatch.setattr(
        "litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.post",
        _fake_post,
    )
    return captured


async def test_litellm_anthropic_effort_and_verbosity_smoke(
    anthropic_request_capture: dict[str, Any],
) -> None:
    """verbosity must not break Anthropic; reasoning_effort must land in output_config."""
    adapter = LiteLLMAdapter(
        AnthropicLLMConfig(
            api_key=SecretStr("sk-ant-test-not-sent"),
            default_model=_MODEL,
            base_url="https://api.anthropic.com",
        ),
    )

    completion = await adapter.generate(
        [ChatMessage(role="user", content="hi")],
        model=_MODEL,
        max_tokens=32,
        reasoning_effort="high",
        verbosity="low",  # OpenAI dial — must be omitted, not raise UnsupportedParamsError
    )

    assert completion.content == "pong"
    payload = anthropic_request_capture.get("json")
    assert isinstance(payload, dict), f"expected Anthropic JSON body, got {payload!r}"
    assert "verbosity" not in payload
    assert payload.get("output_config") == {"effort": "high"}, (
        f"reasoning_effort did not map to output_config.effort; body={json.dumps(payload, default=str)}"
    )
    assert payload.get("max_tokens") == 32
