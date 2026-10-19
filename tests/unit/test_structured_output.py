"""json_schema contract: invariant, provider refusal, formatter fallback vs repair."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pydantic import BaseModel, SecretStr

from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.agents.formatter.repair import complete, generate_document
from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion
from palatium_ai.domain.llm.structured_output import strict_json_schema
from palatium_ai.infrastructure.llm.litellm_adapter import (
    LiteLLMAdapter,
    build_provider_response_format,
    is_structured_output_unsupported,
)


class _Probe(BaseModel):
    task_kind: str
    confidence: float


class _MapProbe(BaseModel):
    """Free-form map field must stay untouched by strictification."""

    labels: dict[str, str]
    note: str


def _no_default_keys(node: object) -> bool:
    if isinstance(node, list):
        return all(_no_default_keys(item) for item in node)
    if isinstance(node, dict):
        return "default" not in node and _no_default_keys(list(node.values()))
    return True


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


def test_strict_json_schema_requires_every_property() -> None:
    from palatium_ai.domain.content import ContentDocument

    schema = strict_json_schema(ContentDocument)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    # `blocks` carries a default_factory; strict mode must still require it — this is
    # the field the model silently dropped on the live gateway before this fix.
    assert "blocks" in schema["required"]
    assert _no_default_keys(schema)


def test_build_provider_response_format_ships_a_strict_clean_schema() -> None:
    from palatium_ai.domain.content import ContentDocument

    payload = build_provider_response_format("json_schema", ContentDocument)
    assert payload is not None
    assert payload["json_schema"]["strict"] is True
    schema = payload["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert _no_default_keys(schema)


def test_strict_json_schema_leaves_map_fields_untouched() -> None:
    schema = strict_json_schema(_MapProbe)
    labels = schema["properties"]["labels"]
    # No `properties` key → not an object with fixed keys; the free-form map stays as-is
    # instead of being collapsed to `additionalProperties: false` + `required`.
    assert labels["additionalProperties"] == {"type": "string"}
    assert "properties" not in labels
    assert "required" not in labels
    assert set(schema["required"]) == {"labels", "note"}


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


def _harness(side_effect: object) -> AsyncMock:
    harness = AsyncMock()
    # Single completion → return_value (LLMCompletion is not a call side-effect iterable).
    if isinstance(side_effect, LLMCompletion):
        harness.call_llm = AsyncMock(return_value=side_effect)
    else:
        harness.call_llm = AsyncMock(side_effect=side_effect)
    return harness


@pytest.mark.asyncio()
async def test_formatter_complete_uses_text_format() -> None:
    body = "Done. No errors."
    harness = _harness(LLMCompletion(content=body, model="test"))
    completion, markdown = await complete(
        harness=harness,
        config=FORMATTER_CONFIG,
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=32,
    )
    assert completion.content == body
    assert markdown == body
    kwargs = harness.call_llm.await_args.kwargs
    assert kwargs["response_format"] == "text"
    assert kwargs["response_model"] is None


@pytest.mark.asyncio()
async def test_formatter_repair_stays_on_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.formatter import FormatterInput
    from palatium_ai.domain.content import CalloutBlock, ContentDocument, DocumentMeta
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    task_input = FormatterInput(
        task_id="t1",
        context_packet=ContextPacket(
            task_id="t1",
            user_text="hi",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="answer",
            requires_mcp=False,
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="r",
            ),
            context_summary="s",
        ),
        worker_summary="Done.",
        response_locale="en-US",
    )
    good = ContentDocument(
        locale="en-US",
        title=None,
        blocks=(CalloutBlock(tone="success", title="Done", body="No errors.", icon="success"),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )
    calls = {"n": 0}

    def _parse(markdown: str, _task: FormatterInput) -> ContentDocument:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        _ = markdown
        return good

    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        _parse,
    )
    harness = _harness(
        [
            LLMCompletion(content="bad", model="test"),
            LLMCompletion(content="> [!SUCCESS]\n> No errors.", model="test"),
        ],
    )
    document = await generate_document(
        harness=harness,
        config=FORMATTER_CONFIG,
        messages=[ChatMessage(role="user", content="hi")],
        task_input=task_input,
        max_tokens=32,
        agent_role=FORMATTER_CONFIG.role,
    )
    assert document.blocks[0].type == "callout"
    formats = [call.kwargs["response_format"] for call in harness.call_llm.await_args_list]
    assert formats == ["text", "text"]
    assert all(call.kwargs["response_model"] is None for call in harness.call_llm.await_args_list)


@pytest.mark.asyncio()
async def test_formatter_does_not_fall_back_on_timeout() -> None:
    harness = _harness(AgentExecutionError("LLM stream timed out"))
    with pytest.raises(AgentExecutionError):
        await complete(
            harness=harness,
            config=FORMATTER_CONFIG,
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=32,
        )
    harness.call_llm.assert_awaited_once()
