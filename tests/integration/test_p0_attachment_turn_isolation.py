"""P0-A.2b: cross-thread attachment must not enter T1 untrusted_context.

Diagnostics only — do not fix get_many / stickiness here. Asserts SoT
``state['untrusted_context']`` (A.1), never derived ``attachment_refs``.

Note: ``FakeDialogTurnStore`` drops ``payload``; SB2 rehydrate needs
``attachment_ids`` on the user turn, so this file uses a local dialog store
that preserves payload (same shape as production DialogTurnStore).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.attachment_service import AttachmentService
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.attachments import AttachmentContent, AttachmentScanSummary
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from tests.conftest import (
    FakeLLMPort,
    SequentialFakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)
from tests.unit.test_attachment_service import _FakeParser, _stack

pytestmark = [pytest.mark.integration(), pytest.mark.asyncio()]

_HITL_HMAC = "integration-p0-hitl-hmac-key-32b"
_USER = "user-p0-iso"
_T1 = "thread-p0-T1"
_T2 = "thread-p0-T2"
_A1_NAME = "otziv_SED_NCPI_RB.pdf"
_A2_NAME = "unrelated.pdf"
_A1_BODY = "MARKER_A1_OTZIV_SED_NCPI_BODY"
_A2_BODY = "MARKER_A2_UNRELATED_BODY"


class _Session:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context


class _ThreadSessionService:
    """Per-thread session context (pending_attachment_ids sticky)."""

    def __init__(self) -> None:
        self._ctx: dict[str, dict[str, object]] = {}

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None

    async def get_session(self, *, thread_id: str) -> _Session:
        return _Session(self._ctx.setdefault(thread_id, {}))

    async def touch_session(self, **kwargs: object) -> None:
        thread_id = str(kwargs["thread_id"])
        patch = kwargs.get("context_patch")
        bucket = self._ctx.setdefault(thread_id, {})
        if isinstance(patch, dict):
            bucket.update(patch)


class _PayloadDialogStore:
    """In-memory dialog store that keeps turn payload (needed for SB2 rehydrate)."""

    def __init__(self) -> None:
        self._turns: dict[str, list[DialogTurn]] = {}

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
        payload: object | None = None,
    ) -> DialogTurn:
        seq = len(self._turns.get(thread_id, []))
        turn = DialogTurn(
            id=uuid4(),
            thread_id=thread_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            task_id=task_id,
            payload=payload if isinstance(payload, dict) else None,
            seq=seq,
            created_at=datetime.now(UTC),
        )
        self._turns.setdefault(thread_id, []).append(turn)
        return turn

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        items = self._turns.get(thread_id, [])[-limit:]
        return DialogTurnWindow(thread_id=thread_id, turns=tuple(items), limit=limit)


def _formatter_json(title: str) -> str:
    import json

    return json.dumps(
        {
            "schema_version": 1,
            "locale": "ru-RU",
            "title": title,
            "blocks": [{"type": "paragraph", "text": title}],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        }
    )


def _intent_knowledge() -> str:
    return (
        '{"task_kind": "knowledge_request", "requires_mcp": false, '
        '"candidate_capabilities": ["summarize"], "confidence": 0.95, '
        '"reasoning": "p0 attachment turn"}'
    )


def _intent_format() -> str:
    return (
        '{"task_kind": "response_formatting", "requires_mcp": false, '
        '"candidate_capabilities": ["format"], "confidence": 0.92, '
        '"reasoning": "p0 format follow-up"}'
    )


def _ctx_new_topic(query: str) -> str:
    return (
        "{"
        f'"rewritten_query": "{query}", '
        '"continuation_kind": "new_topic", '
        '"confidence": 0.9, '
        '"refers_to_prior": false, '
        '"prior_assistant_excerpt": null, '
        '"reasoning": "p0 seed turn"'
        "}"
    )


def _ctx_format(query: str, *, prior: str) -> str:
    prior_escaped = prior.replace('"', '\\"')
    return (
        "{"
        f'"rewritten_query": "{query}", '
        '"continuation_kind": "format", '
        '"confidence": 0.93, '
        '"refers_to_prior": true, '
        f'"prior_assistant_excerpt": "{prior_escaped}", '
        '"reasoning": "p0 file-bound format"'
        "}"
    )


async def _upload_ready(
    service: AttachmentService,
    blob: object,
    parser: _FakeParser,
    *,
    thread_id: str,
    filename: str,
    body: str,
) -> UUID:
    parser._document = ParsedDocument(pages=(ParsedPage(number=1, text=body),))  # type: ignore[attr-defined]
    # Minimal PDF header so mime sniff accepts application/pdf (body text comes from parser).
    payload = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + body.encode("utf-8") + b"\n%%EOF\n"
    ticket = await service.init_upload(
        user_id=_USER,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=len(payload),
        mode="attach",
        thread_id=thread_id,
    )
    row = await service.get(attachment_id=ticket.attachment_id, user_id=_USER)
    await blob.put_direct(row.blob_key, payload, content_type="application/pdf")  # type: ignore[attr-defined]
    saved = await service.complete_upload(attachment_id=ticket.attachment_id, user_id=_USER)
    assert saved.status == "ready"
    assert saved.derived_text_key is not None
    # Pin distinct markers in derived envelope (defence against parser reuse).
    content = AttachmentContent(
        pages=(ParsedPage(number=1, text=body),),
        scan=AttachmentScanSummary(action="allow"),
        safe_text=body,
        page_count=1,
    )
    await blob.write_bytes(  # type: ignore[attr-defined]
        saved.derived_text_key,
        content.model_dump_json().encode("utf-8"),
        content_type="application/json",
    )
    return saved.id


def _build_service(
    *,
    attachment_service: AttachmentService,
    dialog: _PayloadDialogStore,
    sessions: _ThreadSessionService,
    pipeline_responses: list[str],
) -> IntentService:
    pipeline = SequentialFakeLLMPort(pipeline_responses)
    harness = Harness(llm=pipeline)
    graph = build_agent_graph(
        GraphAgents(
            continuation_agent=ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG),
            intent_agent=IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=make_researcher_agent(
                FakeLLMPort('{"summary": "Сводка по вложению.", "confidence": 0.9, "sources_used": ["llm_internal_reasoning"]}'),
                harness=harness,
            ),
            coder_agent=make_coder_agent(harness=harness),
            analyst_agent=make_analyst_agent(harness=harness),
            critic_agent=make_critic_agent(
                FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
            ),
            formatter_agent=make_formatter_agent(FakeLLMPort(_formatter_json("Ответ по файлу"))),
        ),
        harness=harness,
        checkpointer=make_graph_checkpointer(),
    )
    return IntentService(
        graph,  # type: ignore[arg-type]
        session_service=sessions,  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
        attachment_service=attachment_service,
    )


async def test_p0_followup_untrusted_context_stays_on_thread_attachment() -> None:
    """T1 follow-ups must fence A1 only; A2 from T2 must not appear in untrusted_context."""
    parser = _FakeParser(ParsedDocument(pages=(ParsedPage(number=1, text=_A1_BODY),)))
    att_service, blob, _repo = _stack(parser=parser)
    a1_id = await _upload_ready(att_service, blob, parser, thread_id=_T1, filename=_A1_NAME, body=_A1_BODY)
    a2_id = await _upload_ready(att_service, blob, parser, thread_id=_T2, filename=_A2_NAME, body=_A2_BODY)

    dialog = _PayloadDialogStore()
    sessions = _ThreadSessionService()
    prior_excerpt = "Сводка по вложению"
    intent = _build_service(
        attachment_service=att_service,
        dialog=dialog,
        sessions=sessions,
        pipeline_responses=[
            _intent_knowledge(),
            _ctx_new_topic("сводка"),
            _intent_knowledge(),
            _ctx_new_topic("сводка"),
            _intent_format(),
            _ctx_format("покажи полный текст файла", prior=prior_excerpt),
            _intent_format(),
            _ctx_format("план-график", prior=prior_excerpt),
        ],
    )

    captured: list[dict[str, Any]] = []
    runner = intent._graph_runner  # type: ignore[attr-defined]
    original = runner.run_graph

    async def _capture_run_graph(**kwargs: object) -> object:
        state = await original(**kwargs)
        captured.append(dict(state))  # type: ignore[arg-type]
        return state

    runner.run_graph = _capture_run_graph  # type: ignore[method-assign]

    await intent.process(
        text="сводка",
        thread_id=_T1,
        task_id="p0-t1-1",
        user_id=_USER,
        attachment_ids=[a1_id],
    )
    await intent.process(
        text="сводка",
        thread_id=_T2,
        task_id="p0-t2-1",
        user_id=_USER,
        attachment_ids=[a2_id],
    )
    await intent.process(
        text="покажи полный текст файла",
        thread_id=_T1,
        task_id="p0-t1-2",
        user_id=_USER,
    )
    await intent.process(
        text="план-график",
        thread_id=_T1,
        task_id="p0-t1-3",
        user_id=_USER,
    )

    assert len(captured) == 4, f"expected 4 graph finals, got {len(captured)}"
    turn2 = captured[2]
    turn3 = captured[3]
    assert "untrusted_context" in turn2
    assert "untrusted_context" in turn3

    ctx2 = str(turn2.get("untrusted_context") or "")
    ctx3 = str(turn3.get("untrusted_context") or "")

    assert _A1_NAME in ctx2, f"turn2 missing A1 source; untrusted_context={ctx2!r}"
    assert _A2_NAME not in ctx2, f"turn2 LEAKED A2; untrusted_context={ctx2!r}"
    assert _A2_BODY not in ctx2, f"turn2 LEAKED A2 body; untrusted_context={ctx2!r}"

    assert _A1_NAME in ctx3, f"turn3 missing A1 source; untrusted_context={ctx3!r}"
    assert _A2_NAME not in ctx3, f"turn3 LEAKED A2; untrusted_context={ctx3!r}"
    assert _A2_BODY not in ctx3, f"turn3 LEAKED A2 body; untrusted_context={ctx3!r}"
