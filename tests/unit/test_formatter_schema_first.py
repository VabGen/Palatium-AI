"""Formatter schema_first dispatch: json_schema call, fallbacks, mode default (030, 075)."""

from __future__ import annotations

import json

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


def _fenced(document_json: str, *, surrounding_prose: bool = True) -> str:
    """Exactly what the provider returned in the reported incident."""
    preamble = "Вот документ в требуемом формате:\n" if surrounding_prose else ""
    return f"{preamble}```json\n{document_json}\n```"


@pytest.mark.asyncio()
@pytest.mark.parametrize("surrounding_prose", (False, True))
async def test_schema_first_accepts_a_fenced_document(surrounding_prose: bool) -> None:
    """Providers wrap JSON in a Markdown fence even under ``json_schema`` (2026-10-30)."""
    harness = _StubHarness([LLMCompletion(content=_fenced(_document_json(), surrounding_prose=surrounding_prose), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert output.output.title == "Status"
    # Decoded, not retried: no second (legacy) generation for a formatting slip.
    assert [call["response_format"] for call in harness.calls] == ["json_schema"]


@pytest.mark.asyncio()
async def test_schema_first_survives_a_document_without_meta() -> None:
    """A dropped ``meta`` is a decode default, not a reason to regenerate the answer."""
    raw = json.loads(_document_json())
    del raw["meta"]
    harness = _StubHarness([LLMCompletion(content=_fenced(json.dumps(raw, ensure_ascii=False)), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert output.output.blocks == ContentDocument.model_validate_json(_document_json()).blocks
    assert [call["response_format"] for call in harness.calls] == ["json_schema"]


@pytest.mark.asyncio()
async def test_schema_first_drops_an_unknown_icon_instead_of_the_block() -> None:
    """Unknown icon names are chrome: coerce drops them, tone fill may restore a registry token.

    ``PresentationIconPolicy`` assigns missing callout icons from ``tone`` after parse —
    so the invariant is "document-check never survives", not "icon stays None".
    """
    raw = json.loads(_document_json())
    raw["blocks"][0]["icon"] = "document-check"
    harness = _StubHarness([LLMCompletion(content=json.dumps(raw, ensure_ascii=False), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    callout = output.output.blocks[0]
    assert isinstance(callout, CalloutBlock)
    assert callout.icon != "document-check"
    assert callout.icon == "success"  # tone default after unknown drop (PresentationIconPolicy)
    assert callout.body == "No errors."
    assert [call["response_format"] for call in harness.calls] == ["json_schema"]


@pytest.mark.asyncio()
async def test_schema_first_falls_back_on_truncated_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cut-off payload is a model defect: the legacy contract retries, no stack trace."""
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    truncated = _document_json()[: len(_document_json()) // 2]
    harness = _StubHarness(
        [
            LLMCompletion(content=truncated, model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]
    before = _schema_count("schema_first", "invalid")

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert [call["response_format"] for call in harness.calls] == ["json_schema", "text"]
    assert _schema_count("schema_first", "invalid") == before + 1


@pytest.mark.asyncio()
async def test_schema_first_unwraps_a_nested_document_payload() -> None:
    """Some gateways answer with ``{"document": {...}}`` around the schema payload."""
    harness = _StubHarness([LLMCompletion(content=json.dumps({"document": json.loads(_document_json())}), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert output.output.title == "Status"
    assert [call["response_format"] for call in harness.calls] == ["json_schema"]


@pytest.mark.asyncio()
async def test_schema_first_invalid_document_log_carries_no_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator gets the failing field; the model's prose stays out of the logs (020)."""
    from structlog.testing import capture_logs

    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    leaked = "секретный текст клиента"
    raw = json.loads(_document_json())
    # ``body`` is required: the payload fails validation and its prose is what a
    # ``str(ValidationError)`` would have echoed into the log.
    raw["blocks"] = [{"type": "callout", "tone": "info", "text": leaked}]
    harness = _StubHarness(
        [
            LLMCompletion(content=json.dumps(raw, ensure_ascii=False), model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

    with capture_logs() as logs:
        await agent.run(_agent_input())

    assert any(entry.get("event") == "formatter.schema_first.invalid_json" for entry in logs)
    assert all(leaked not in str(entry) for entry in logs)


@pytest.mark.asyncio()
async def test_schema_first_falls_back_when_the_payload_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An array-wrapped answer is a model defect: retry on the legacy contract."""
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness(
        [
            LLMCompletion(content=f"[{_document_json()}]", model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]

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


@pytest.mark.asyncio()
async def test_schema_metric_counts_a_valid_document_under_schema_first() -> None:
    harness = _StubHarness([LLMCompletion(content=_document_json(), model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]
    before = _schema_count("schema_first", "valid")

    await agent.run(_agent_input())

    assert _schema_count("schema_first", "valid") == before + 1


@pytest.mark.asyncio()
async def test_schema_metric_separates_invalid_json_from_a_content_defect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``invalid`` is a prompt/model signal; ``empty_blocks`` is a content defect."""
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    empty = ContentDocument(locale="en-US", blocks=(), meta=DocumentMeta(confidence=0.95))
    harness = _StubHarness(
        [
            LLMCompletion(content="{not-a-document", model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
            LLMCompletion(content=empty.model_dump_json(), model="test"),
            LLMCompletion(content="Done. No errors.", model="test"),
        ]
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first")  # type: ignore[arg-type]
    invalid_before = _schema_count("schema_first", "invalid")
    empty_before = _schema_count("schema_first", "empty_blocks")

    await agent.run(_agent_input())
    await agent.run(_agent_input())

    assert _schema_count("schema_first", "invalid") == invalid_before + 1
    assert _schema_count("schema_first", "empty_blocks") == empty_before + 1


@pytest.mark.asyncio()
async def test_schema_metric_marks_provider_refusal_as_having_no_verdict(
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
    before = _schema_count("schema_first", "unsupported")

    await agent.run(_agent_input())

    assert _schema_count("schema_first", "unsupported") == before + 1


@pytest.mark.asyncio()
async def test_schema_metric_records_the_legacy_contract_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    harness = _StubHarness([LLMCompletion(content="Done. No errors.", model="test")])
    agent = FormatterAgent(harness, FORMATTER_CONFIG)  # type: ignore[arg-type]
    before = _schema_count("legacy_markdown", "valid")

    await agent.run(_agent_input())

    assert _schema_count("legacy_markdown", "valid") == before + 1


def _schema_count(path: str, outcome: str) -> int:
    from palatium_ai.core.observability.metrics import agent_metrics

    return agent_metrics.formatter_schema_count(path, outcome)


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


@pytest.mark.asyncio()
async def test_provider_citations_are_counted_and_never_rewrite_the_answer() -> None:
    """W3a: a citation is resolved against the text it annotates, or counted as dropped.

    The answer itself is untouched — the citation anchor is telemetry until W3b can
    show a source viewer, and a wrong anchor must not become a confident chip.
    """
    from palatium_ai.core.observability.metrics import agent_metrics
    from palatium_ai.domain.content.citations import CitationRef

    raw = _document_json(kind="report")
    resolved = CitationRef(source_ref="policy.pdf", answer_range=(0, 5), anchor="url_only")
    past_the_end = CitationRef(source_ref="policy.pdf", answer_range=(0, len(raw) + 10), anchor="url_only")
    harness = _StubHarness(
        [LLMCompletion(content=raw, model="test", citations=(resolved, resolved, past_the_end))],
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="schema_first", rollout_pct=100)  # type: ignore[arg-type]
    before_resolved = agent_metrics.citation_resolution_count("url_only", "resolved")
    before_range = agent_metrics.citation_resolution_count("url_only", "out_of_range")

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert output.output.blocks == ContentDocument.model_validate_json(raw).blocks
    # Duplicates still count as emitted (denominator honesty), resolution does not.
    assert agent_metrics.citation_resolution_count("url_only", "resolved") == before_resolved + 2
    assert agent_metrics.citation_resolution_count("url_only", "out_of_range") == before_range + 1
    # W3b: the resolved anchor reaches the client, the dropped one never does.
    assert output.output.meta.citations == (resolved,)


@pytest.mark.asyncio()
async def test_legacy_attaches_provider_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy Markdown path still surfaces W3a anchors when DocumentParts are cited."""
    from palatium_ai.domain.content.citations import CitationRef

    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.repair.markdown_to_content_document",
        lambda _raw, _task: _fixed_document(),
    )
    citation = CitationRef(
        source_ref="policy.pdf",
        quote=None,
        source_range=(0, 12),
        anchor="char_location",
    )
    harness = _StubHarness(
        [LLMCompletion(content="Done. No errors.", model="test", citations=(citation,))],
    )
    agent = FormatterAgent(harness, FORMATTER_CONFIG, mode="legacy", rollout_pct=0)  # type: ignore[arg-type]

    output = await agent.run(_agent_input())

    assert isinstance(output.output, ContentDocument)
    assert output.output.meta.citations == (citation,)


def test_citation_anchors_are_not_part_of_the_provider_schema() -> None:
    """W3b: the model must never be *asked* for anchors it cannot know.

    ``ContentDocument`` is the provider's strict output schema, where every property
    is required. Listing ``citations`` there would make the model invent offsets;
    ``SkipJsonSchema`` keeps the field on the wire (server → client) only.
    """
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.llm.structured_output import strict_json_schema

    meta_schema = strict_json_schema(ContentDocument)["$defs"]["DocumentMeta"]

    assert "citations" not in meta_schema["properties"]
    assert "citations" not in meta_schema["required"]


def test_citation_anchors_are_serialised_for_the_client() -> None:
    """The other half of the same contract: absent from the LLM schema, present in JSON."""
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.content.citations import CitationRef

    citation = CitationRef(source_ref="policy.pdf", quote="Оплата в течение 5 дней", page=2, anchor="page_location")
    document = ContentDocument.model_validate_json(_document_json())
    with_citation = document.model_copy(update={"meta": document.meta.model_copy(update={"citations": (citation,)})})

    payload = with_citation.model_dump(mode="json")

    assert payload["meta"]["citations"][0]["source_ref"] == "policy.pdf"
    assert payload["meta"]["citations"][0]["page"] == 2
    # An older/legacy payload without the field stays valid.
    assert document.meta.citations == ()


def _context_packet_json_shaped(shape: str) -> str:
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    return ContextPacket(
        task_id="t1",
        user_text="make a plan",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="r"),
        context_summary="s",
        response_shape=shape,  # type: ignore[arg-type]
    ).model_dump_json()


def _plan_document_json() -> str:
    from palatium_ai.domain.content import ContentDocument, DocumentMeta, StepItem, StepsBlock

    document = ContentDocument(
        locale="en-US",
        title="Plan",
        blocks=(
            StepsBlock(
                items=(
                    StepItem(title="Gather inputs", body="Collect requirements"),
                    StepItem(title="Draft", body="Write the outline"),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.92, kind="report", formality="neutral"),
    )
    return document.model_dump_json()


def _prose_document_json() -> str:
    from palatium_ai.domain.content import ContentDocument, DocumentMeta, ParagraphBlock

    document = ContentDocument(
        locale="en-US",
        title="Prose",
        blocks=(ParagraphBlock(text="Just a paragraph, not a plan."),),
        meta=DocumentMeta(confidence=0.9, kind="report", formality="neutral"),
    )
    return document.model_dump_json()


@pytest.mark.asyncio()
async def test_shape_precheck_buffers_then_emits_without_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FORMATTER_SHAPE_PRECHECK uses call_llm (not stream) and paints once at the end."""
    emitted: list[str] = []
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.agent.emit_content_document",
        lambda doc: emitted.append(doc.title or ""),
    )
    harness = _StubHarness([LLMCompletion(content=_plan_document_json(), model="test")])
    agent = FormatterAgent(
        harness,
        FORMATTER_CONFIG,
        mode="schema_first",
        rollout_pct=100,
        shape_precheck=True,
    )  # type: ignore[arg-type]
    agent_input = AgentInput(
        task_id=UUID(int=1),
        trace_id="t",
        instruction="format",
        context={
            "context_packet_json": _context_packet_json_shaped("plan"),
            "worker_summary": "Done.",
        },
    )

    output = await agent.run(agent_input)

    assert isinstance(output.output, ContentDocument)
    assert output.output.title == "Plan"
    assert emitted == ["Plan"]
    # Buffered path: only call_llm, never the stream paint loop.
    assert harness.calls == [{"response_format": "json_schema", "response_model": ContentDocument}]


@pytest.mark.asyncio()
async def test_shape_precheck_regenerates_once_on_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mismatch before paint → one regenerate; second document is what the UI sees."""
    from palatium_ai.core.observability.metrics import agent_metrics

    emitted: list[str] = []
    monkeypatch.setattr(
        "palatium_ai.application.agents.formatter.agent.emit_content_document",
        lambda doc: emitted.append(doc.title or ""),
    )
    before_mismatch = agent_metrics.response_shape_count("plan", "precheck_mismatch")
    before_regen = agent_metrics.response_shape_count("plan", "precheck_regenerated")
    harness = _StubHarness(
        [
            LLMCompletion(content=_prose_document_json(), model="test"),
            LLMCompletion(content=_plan_document_json(), model="test"),
        ]
    )
    agent = FormatterAgent(
        harness,
        FORMATTER_CONFIG,
        mode="schema_first",
        rollout_pct=100,
        shape_precheck=True,
    )  # type: ignore[arg-type]
    agent_input = AgentInput(
        task_id=UUID(int=2),
        trace_id="t",
        instruction="format",
        context={
            "context_packet_json": _context_packet_json_shaped("plan"),
            "worker_summary": "Done.",
        },
    )

    output = await agent.run(agent_input)

    assert isinstance(output.output, ContentDocument)
    assert output.output.title == "Plan"
    assert emitted == ["Plan"]
    assert len(harness.calls) == 2
    assert agent_metrics.response_shape_count("plan", "precheck_mismatch") == before_mismatch + 1
    assert agent_metrics.response_shape_count("plan", "precheck_regenerated") == before_regen + 1
