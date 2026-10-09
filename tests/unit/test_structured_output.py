"""json_schema contract: invariant, provider refusal, formatter fallback vs repair."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pydantic import BaseModel, SecretStr

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.domain.content import CalloutBlock, ContentDocument, DocumentMeta
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion
from palatium_ai.infrastructure.llm.litellm_adapter import (
    LiteLLMAdapter,
    is_structured_output_unsupported,
)


class _Probe(BaseModel):
    task_kind: str
    confidence: float


def _document_json() -> str:
    document = ContentDocument(
        locale="en-US",
        title=None,
        blocks=(CalloutBlock(tone="success", title="Done", body="No errors.", icon="success"),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )
    return document.model_dump_json()


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hi")]


class _RecordingLLM:
    def __init__(self, *, error: Exception | None = None, content: str = "{}") -> None:
        self.calls = 0
        self.error = error
        self.content = content

    async def generate(self, messages: list[ChatMessage], **kwargs: object) -> LLMCompletion:
        _ = messages, kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMCompletion(content=self.content, model="test")


def test_unsupported_detector_ignores_invalid_schema_and_timeouts() -> None:
    assert is_structured_output_unsupported(RuntimeError("response_format json_schema is not supported"))
    assert is_structured_output_unsupported(RuntimeError("strict mode is unsupported for this model"))
    assert not is_structured_output_unsupported(RuntimeError("invalid_schema: additionalProperties"))
    assert not is_structured_output_unsupported(RuntimeError("invalid schema"))
    assert not is_structured_output_unsupported(TimeoutError())


@pytest.mark.asyncio()
async def test_harness_requires_response_model_before_the_provider() -> None:
    llm = _RecordingLLM()
    harness = Harness(llm=llm)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="response_model is required"):
        await harness.call_llm(
            FORMATTER_CONFIG,
            _messages(),
            response_format="json_schema",
        )
    assert llm.calls == 0


@pytest.mark.asyncio()
async def test_harness_does_not_retry_structured_output_refusal() -> None:
    llm = _RecordingLLM(error=StructuredOutputUnsupportedError("nope"))
    harness = Harness(llm=llm)  # type: ignore[arg-type]
    config = FORMATTER_CONFIG.model_copy(update={"max_retries": 3})
    with pytest.raises(StructuredOutputUnsupportedError):
        await harness.call_llm(
            config,
            _messages(),
            response_format="json_schema",
            response_model=_Probe,
        )
    assert llm.calls == 1


@pytest.mark.asyncio()
async def test_adapter_translates_only_an_explicit_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refuse(**_kwargs: object) -> object:
        raise RuntimeError("response_format json_schema is not supported")

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _refuse)
    adapter = LiteLLMAdapter(
        QwenLLMConfig(
            api_key=SecretStr("test-key"),
            base_url="http://127.0.0.1:9/v1",
            default_model="generative-model",
        ),
    )
    with pytest.raises(StructuredOutputUnsupportedError):
        await adapter.generate(
            _messages(),
            response_format="json_schema",
            response_model=_Probe,
        )


@pytest.mark.asyncio()
async def test_adapter_keeps_invalid_schema_as_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _invalid(**_kwargs: object) -> object:
        raise RuntimeError("invalid_schema: strict schema rejected")

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _invalid)
    adapter = LiteLLMAdapter(
        QwenLLMConfig(
            api_key=SecretStr("test-key"),
            base_url="http://127.0.0.1:9/v1",
            default_model="generative-model",
        ),
    )
    with pytest.raises(RuntimeError, match="invalid_schema"):
        await adapter.generate(
            _messages(),
            response_format="json_schema",
            response_model=_Probe,
        )


def _agent(side_effect: object) -> tuple[FormatterAgent, AsyncMock]:
    harness = AsyncMock()
    harness.call_llm = AsyncMock(side_effect=side_effect)
    return FormatterAgent(harness, FORMATTER_CONFIG), harness


@pytest.mark.asyncio()
async def test_formatter_falls_back_only_on_structured_output_refusal() -> None:
    body = _document_json()
    agent, harness = _agent([StructuredOutputUnsupportedError("nope"), LLMCompletion(content=body, model="test")])
    document = await agent._complete([ChatMessage(role="user", content="hi")], max_tokens=32)
    assert document.content == body
    formats = [call.kwargs["response_format"] for call in harness.call_llm.await_args_list]
    assert formats == ["json_schema", "json_object"]
    assert harness.call_llm.await_args_list[0].kwargs["response_model"] is ContentDocument
    assert harness.call_llm.await_args_list[1].kwargs["response_model"] is None


@pytest.mark.asyncio()
async def test_formatter_repair_stays_on_json_schema() -> None:
    body = _document_json()
    agent, harness = _agent(
        [
            LLMCompletion(content="{not-json", model="test"),
            LLMCompletion(content=body, model="test"),
        ],
    )
    document = await agent._generate_document([ChatMessage(role="user", content="hi")], max_tokens=32)
    assert document.blocks[0].type == "callout"
    formats = [call.kwargs["response_format"] for call in harness.call_llm.await_args_list]
    assert formats == ["json_schema", "json_schema"]


@pytest.mark.asyncio()
async def test_formatter_does_not_fall_back_on_timeout() -> None:
    agent, harness = _agent(AgentExecutionError("LLM stream timed out"))
    with pytest.raises(AgentExecutionError):
        await agent._complete([ChatMessage(role="user", content="hi")], max_tokens=32)
    harness.call_llm.assert_awaited_once()
