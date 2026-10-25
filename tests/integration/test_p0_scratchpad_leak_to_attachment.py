"""P0-A.2d / P0-B: polluted scratchpad + user-ns must not retarget T1 fence to A2.

H4: cross-session user_namespace facts about a foreign attachment used to bleed
into T1 ``memory_hits``. Fence path stayed clean (A.2b); Select kind-gate (P0-B)
must keep foreign user-ns facts out of hot-path recall.
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
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.domain.attachments import AttachmentContent, AttachmentScanSummary
from palatium_ai.domain.attachments.citations import citation_refs_from_untrusted_context
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
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

_HITL_HMAC = "integration-p0d-hitl-hmac-key-32b"
_USER = "user-p0-scratch"
_T1 = "thread-p0d-T1"
_T2 = "thread-p0d-T2"
_A1_NAME = "otziv_SED_NCPI_RB.pdf"
_A2_NAME = "unrelated.pdf"
_A1_BODY = "MARKER_A1_OTZIV_SED_NCPI_BODY"
_A2_BODY = "MARKER_A2_UNRELATED_BODY"
_T2_SCRATCH_MARKER = "P0D_T2_SCRATCHPAD_FOREIGN_SESSION"
_USER_NS_MARKER = "P0D_USER_NS_FOREIGN_ATTACHMENT"
_FOLLOW_UP = "покажи полный текст файла"


class _Session:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context


class _ThreadSessionService:
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
        '"reasoning": "p0d knowledge"}'
    )


def _ctx_new_topic(query: str) -> str:
    return (
        "{"
        f'"rewritten_query": "{query}", '
        '"continuation_kind": "new_topic", '
        '"confidence": 0.9, '
        '"refers_to_prior": false, '
        '"prior_assistant_excerpt": null, '
        '"reasoning": "p0d seed"'
        "}"
    )


def _ctx_answer(query: str, *, prior: str) -> str:
    prior_escaped = prior.replace('"', '\\"')
    return (
        "{"
        f'"rewritten_query": "{query}", '
        '"continuation_kind": "answer", '
        '"confidence": 0.93, '
        '"refers_to_prior": true, '
        f'"prior_assistant_excerpt": "{prior_escaped}", '
        '"reasoning": "p0d file follow-up; ambiguity between letter and contract"'
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
    memory_port: InMemoryMemoryPort,
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
        memory_port=memory_port,
        attachment_service=attachment_service,
        recall_max_items=8,
        recall_max_chars=2000,
    )


async def _capture_states(intent: IntentService) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    runner = intent._graph_runner  # type: ignore[attr-defined]
    original = runner.run_graph

    async def _capture_run_graph(
        *,
        text: str,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
        tenant_key: str | None = None,
        revision_feedback: str | None = None,
        untrusted_context: str = "",
        # AttachmentContext arrives with the fenced turn body (P0): the double must
        # accept it, otherwise the process() call fails before the graph is reached.
        attachment_context: object | None = None,
        exclude_trailing_user: bool = True,
        trace_id: str | None = None,
    ) -> object:
        state = await original(
            text=text,
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=tenant_key,
            revision_feedback=revision_feedback,
            untrusted_context=untrusted_context,
            attachment_context=attachment_context,  # type: ignore[arg-type]
            exclude_trailing_user=exclude_trailing_user,
            trace_id=trace_id,
        )
        captured.append(dict(state))  # type: ignore[arg-type]
        return state

    runner.run_graph = _capture_run_graph  # type: ignore[method-assign]
    return captured


async def test_p0_polluted_scratchpad_does_not_retarget_t1_fence_to_a2() -> None:
    """T2 scratchpad + user-ns facts about A2 must not fence A2 into T1 follow-up."""
    parser = _FakeParser(ParsedDocument(pages=(ParsedPage(number=1, text=_A1_BODY),)))
    att_service, blob, _repo = _stack(parser=parser)
    a1_id = await _upload_ready(att_service, blob, parser, thread_id=_T1, filename=_A1_NAME, body=_A1_BODY)
    a2_id = await _upload_ready(att_service, blob, parser, thread_id=_T2, filename=_A2_NAME, body=_A2_BODY)

    memory = InMemoryMemoryPort()
    await SessionScratchpadService(memory).save(
        SessionScratchpad(
            thread_id=_T2,
            slots=(
                ScratchpadSlot(
                    key="foreign-attachment-id",
                    text=(f"{_T2_SCRATCH_MARKER} {_FOLLOW_UP} {_A2_NAME} id={a2_id}"),
                    kind="fact",
                ),
            ),
        )
    )
    await memory.put(
        namespace=user_namespace(_USER),
        key="foreign-file",
        value={
            "text": (f"{_USER_NS_MARKER} past session asked '{_FOLLOW_UP}' about {_A2_NAME} id={a2_id}"),
            "kind": "fact",
            "confidence": 0.95,
        },
    )

    dialog = _PayloadDialogStore()
    sessions = _ThreadSessionService()
    prior_excerpt = "Сводка по вложению"
    intent = _build_service(
        attachment_service=att_service,
        dialog=dialog,
        sessions=sessions,
        memory_port=memory,
        pipeline_responses=[
            _intent_knowledge(),
            _ctx_new_topic("сводка"),
            _intent_knowledge(),
            _ctx_new_topic("сводка"),
            _intent_knowledge(),
            _ctx_answer(_FOLLOW_UP, prior=prior_excerpt),
        ],
    )
    captured = await _capture_states(intent)

    await intent.process(
        text="сводка",
        thread_id=_T1,
        task_id="p0d-t1-1",
        user_id=_USER,
        attachment_ids=[a1_id],
    )
    await intent.process(
        text="сводка",
        thread_id=_T2,
        task_id="p0d-t2-1",
        user_id=_USER,
        attachment_ids=[a2_id],
    )
    await intent.process(
        text=_FOLLOW_UP,
        thread_id=_T1,
        task_id="p0d-t1-2",
        user_id=_USER,
    )

    assert len(captured) == 3, f"expected 3 finals, got {len(captured)}"
    turn2 = captured[2]
    ctx = str(turn2.get("untrusted_context") or "")
    refs = citation_refs_from_untrusted_context(ctx)
    recall = turn2.get("memory_recall")
    hints = "\n".join(str(getattr(hit, "text", "")) for hit in (getattr(recall, "hits", ()) or ()))

    assert _A1_NAME in ctx, f"turn2 missing A1; untrusted_context={ctx!r}"
    assert _A2_NAME not in ctx, f"H4 attachment path: A2 LEAKED into fence; untrusted_context={ctx!r}"
    assert _A2_BODY not in ctx, f"H4 attachment path: A2 body LEAKED; untrusted_context={ctx!r}"
    assert str(a2_id) not in ctx, f"H4 attachment path: A2 uuid LEAKED; untrusted_context={ctx!r}"
    assert refs == (_A1_NAME,), f"attachment_refs={refs!r}"

    assert _T2_SCRATCH_MARKER not in hints, f"H4 scratchpad cross-thread: T2 pad loaded on T1; memory_hits={hints!r}"
    assert _USER_NS_MARKER not in hints, f"H4 user-ns bleed into T1 memory_hits; memory_hits={hints!r}"
    assert _A2_NAME not in hints, f"H4 A2 filename in T1 memory_hits; memory_hits={hints!r}"
