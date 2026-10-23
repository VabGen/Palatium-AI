# tests/unit/test_llm_shared_transport.py

"""The LiteLLM call must reuse one HTTP session instead of leaking one per request (080).

Regression: every ``acompletion`` without ``shared_session`` made LiteLLM build and
abandon an ``aiohttp.ClientSession``; the GC then logged ``Unclosed client session``
and sockets stayed open until collection.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aiohttp import ClientSession

from palatium_ai.core.config.llm.openai import OpenAILLMConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.infrastructure.llm import shared_transport
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

_LLM_ACOMPLETION = "palatium_ai.infrastructure.llm.litellm_adapter.acompletion"


def _config() -> OpenAILLMConfig:
    return OpenAILLMConfig.model_validate({"OPENAI_API_KEY": "k", "OPENAI_TIMEOUT": "42"})


async def _call(monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, object]]) -> None:
    async def _fake_acompletion(**params: object) -> object:
        captured.append(params)
        return SimpleNamespace(choices=[], model="gpt-4o", usage=None)

    monkeypatch.setattr(_LLM_ACOMPLETION, _fake_acompletion)
    await LiteLLMAdapter(_config()).generate([ChatMessage(role="user", content="hi")])


@pytest.mark.asyncio()
async def test_generate_passes_one_shared_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    await _call(monkeypatch, captured)
    await _call(monkeypatch, captured)

    first = captured[0]["shared_session"]
    assert isinstance(first, ClientSession)
    assert not first.closed
    # The second request must reuse the same session — a new one per call is the leak.
    assert captured[1]["shared_session"] is first


@pytest.mark.asyncio()
async def test_shutdown_closes_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    await _call(monkeypatch, captured)
    session = captured[0]["shared_session"]
    assert isinstance(session, ClientSession)
    connector = session.connector

    await shared_transport.aclose_shared_client_sessions()

    assert session.closed
    assert connector is not None
    assert connector.closed
    assert shared_transport._sessions == {}  # the registry is the contract under test
