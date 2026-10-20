"""Formatter schema_first dispatch: json_schema call, fallbacks, mode default (030, 075)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.content import (
    CalloutBlock,
    ContentDocument,
    DocumentMeta,
)
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import LLMCompletion, LLMResponseFormat

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.content import DocumentKind, FormalityLevel


class _StubHarness:
    """Minimal HarnessPort: records each call and returns/raises scripted items."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def call_llm(
        self,
        config: AgentConfig,
        messages: list[object],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        _ = config, messages, max_tokens
        self.calls.append({"response_format": response_format, "response_model": response_model})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, LLMCompletion)
        return item

    async def call_llm_stream(
        self,
        config: AgentConfig,
        messages: list[object],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        on_delta: object = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        """Same scripted response, delivered incrementally so the scanner can paint."""
        completion = await self.call_llm(
            config,
            messages,
            response_format=response_format,
            response_model=response_model,
            max_tokens=max_tokens,
        )
        if callable(on_delta):
            for start in range(0, len(completion.content), 40):
                on_delta(completion.content[start : start + 40])
        return completion


def _context_packet_json() -> str:
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    return ContextPacket(
        task_id="t1",
        user_text="hi",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="r"),
        context_summary="s",
    ).model_dump_json()


def _agent_input() -> AgentInput:
    return AgentInput(
        task_id=UUID(int=1),
        trace_id="t",
        instruction="format",
        # No response_locale → "und" → legacy locale-repair gate short-circuits.
        context={"context_packet_json": _context_packet_json(), "worker_summary": "Done."},
    )


def _document_json(*, kind: DocumentKind = "report", formality: FormalityLevel = "neutral") -> str:
    document = ContentDocument(
        locale="en-US",
        title="Status",
        blocks=(CalloutBlock(tone="success", title="Done", body="No errors.", icon="success"),),
        meta=DocumentMeta(confidence=0.9, kind=kind, formality=formality),
    )
    return document.model_dump_json()


def _fixed_document() -> ContentDocument:
    return ContentDocument(
        locale="en-US",
        title=None,
        blocks=(CalloutBlock(tone="success", title="Done", body="No errors."),),
        meta=DocumentMeta(confidence=0.9),
    )


@pytest.mark.asyncio()
async def test_schema_first_requests_json_schema_with_the_model() -> None:
    harness = _StubHarness([LLMCompletion(content=_document_json(kind="report"), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert output.status == "success"
    assert isinstance(output.output, ContentDocument)
    assert output.output.meta.kind == "report"
    assert harness.calls == [{"response_format": "json_schema", "response_model": ContentDocument}]


@pytest.mark.asyncio()
async def test_schema_first_falls_back_to_legacy_on_provider_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness(
        [
            StructuredOutputUnsupportedError("no json_schema"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert [call["response_format"] for call in harness.calls] == ["json_schema", "text"]


@pytest.mark.asyncio()
async def test_schema_first_falls_back_to_legacy_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness(
        [
            LLMCompletion(content="{not-a-document", model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert [call["response_format"] for call in harness.calls] == ["json_schema", "text"]


@pytest.mark.asyncio()
async def test_schema_first_falls_back_when_the_model_drops_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-empty answer with no blocks is a silent failure, not a valid document."""
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    empty = ContentDocument(locale="en-US", blocks=(), meta=DocumentMeta(confidence=0.95))
    harness = _StubHarness(
        [
            LLMCompletion(content=empty.model_dump_json(), model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert [call["response_format"] for call in harness.calls] == ["json_schema", "text"]


@pytest.mark.asyncio()
async def test_legacy_mode_never_requests_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness([LLMCompletion(content="Done. No errors.", model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG)  # type: ignore[arg-type]

    assert agent.mode == "legacy"
    await agent.run(_agent_input())

    assert all(call["response_format"] == "text" for call in harness.calls)


def test_document_meta_kind_and_formality_defaults_are_non_breaking() -> None:
    meta = DocumentMeta(confidence=0.8)
    assert meta.kind == "analysis"
    assert meta.formality == "neutral"
    explicit = DocumentMeta(confidence=0.8, kind="letter", formality="official")
    assert explicit.kind == "letter"
    assert explicit.formality == "official"


def test_resolve_formatter_mode_two_key_semantics() -> None:
    from palatium_ai.core.observability.formatter_rollout import resolve_formatter_mode

    # legacy target wins regardless of coverage.
    assert resolve_formatter_mode("legacy", 100, "u1") == "legacy"
    assert resolve_formatter_mode("legacy", 0, "u1") == "legacy"
    # schema_first target still needs coverage > 0 (a lone MODE flip must not cut everyone over).
    assert resolve_formatter_mode("schema_first", 0, "u1") == "legacy"
    assert resolve_formatter_mode("schema_first", 100, "u1") == "schema_first"


def test_resolve_formatter_mode_is_sticky_and_bucketed() -> None:
    from palatium_ai.core.observability.formatter_rollout import resolve_formatter_mode
    from palatium_ai.core.observability.redaction import hash8

    uid = "user-42"
    bucket = int(hash8(uid), 16) % 100
    # 1..99 is the sticky cohort: the same caller always lands on the same contract.
    assert resolve_formatter_mode("schema_first", bucket + 1, uid) == "schema_first"
    assert resolve_formatter_mode("schema_first", bucket, uid) == "legacy"
    assert resolve_formatter_mode("schema_first", 50, uid) == resolve_formatter_mode("schema_first", 50, uid)
    # Anonymous callers are bucketed, not blanket-excluded.
    assert resolve_formatter_mode("schema_first", 100, None) == "schema_first"


@pytest.mark.asyncio()
async def test_rollout_zero_coverage_pins_schema_first_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MODE=schema_first with PCT=0 must run the legacy contract, not the canary."""
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness([LLMCompletion(content="Done. No errors.", model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=0)  # type: ignore[arg-type]

    await agent.run(_agent_input())

    assert all(call["response_format"] == "text" for call in harness.calls)


@pytest.mark.asyncio()
async def test_rollout_full_coverage_uses_an_explicit_user_id_from_context() -> None:
    from palatium_ai.core.logging.context import user_id_var

    harness = _StubHarness([LLMCompletion(content=_document_json(kind="guide"), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    token = user_id_var.set("user-42")
    try:
        output = await agent.run(_agent_input())
    finally:
        user_id_var.reset(token)

    assert isinstance(output.output, ContentDocument)
    assert harness.calls == [{"response_format": "json_schema", "response_model": ContentDocument}]


@pytest.mark.asyncio()
async def test_run_records_mode_split_latency_for_the_canary() -> None:
    """Both cohorts share a process, so the A/B latency needs a mode label (Phase 3)."""
    from palatium_ai.core.observability.metrics import agent_metrics

    harness = _StubHarness([LLMCompletion(content=_document_json(kind="report"), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    before = agent_metrics.node_execution_count("formatter", "formatter:schema_first")
    await agent.run(_agent_input())

    assert agent_metrics.node_execution_count("formatter", "formatter:schema_first") == before + 1


@pytest.mark.asyncio()
async def test_schema_first_paints_blocks_incrementally_without_replacing() -> None:
    """The streamed document is a superset of the preview — no replace frame at all."""
    from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge

    harness = _StubHarness([LLMCompletion(content=_document_json(kind="report"), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]
    bridge = TurnSseBridge(stream_contract="structured_incremental")

    with turn_sse_bridge(bridge):
        output = await agent.run(_agent_input())

    events = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    frames = [event for event in events if event.get("event") == "answer_delta"]
    assert frames, "structured contract must paint before the document is validated"
    assert all("replace" not in frame for frame in frames)
    painted = "".join(str(frame["delta"]) for frame in frames)
    # Preview prose == document prose (superset, not a different text).
    assert "Status" in painted
    assert "Done" in painted
    assert "No errors." in painted
    blocks = [event for event in events if event.get("event") == "block_delta"]
    assert len(blocks) == 1
    assert blocks[0]["index"] == 0
    streamed_block = ContentDocument.model_validate_json(_document_json()).blocks[0]
    assert blocks[0]["block"] == streamed_block.model_dump(mode="json")
    assert isinstance(output.output, ContentDocument)
    # Streamed, not buffered: the same call carries the schema.
    assert harness.calls == [{"response_format": "json_schema", "response_model": ContentDocument}]


@pytest.mark.asyncio()
async def test_schema_first_paints_nothing_when_the_provider_refuses_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal must not leave a half preview: legacy takes over from a clean slate."""
    from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge

    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness(
        [
            StructuredOutputUnsupportedError("no json_schema"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]
    bridge = TurnSseBridge(stream_contract="structured_incremental")

    with turn_sse_bridge(bridge):
        output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert [call["response_format"] for call in harness.calls] == ["json_schema", "text"]
