"""P0-A.2e: dialog prior / pending / scratchpad vs fence (H5 / H6).

A.2d showed user-ns memory bleed without fence retarget. A.2e checks whether
wrong-file fence can come from dialog prior (H5) or pending (H6), and whether
``attachment_refs`` can be derived from scratchpad text (user concern).

Diagnostics only — do not fix src/.
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
from palatium_ai.application.services.intent_turn_helpers import (
    PENDING_ATTACHMENT_IDS_KEY,
    serialize_pending_attachment_ids,
)
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.domain.attachments import AttachmentContent, AttachmentScanSummary
from palatium_ai.domain.attachments.citations import citation_refs_from_untrusted_context
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow, parse_turn_attachment_ids
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

_HITL_HMAC = "integration-p0e-hitl-hmac-key-32b"
_USER = "user-p0-dialog"
_T1 = "thread-p0e-T1"
_T2 = "thread-p0e-T2"
_A1_NAME = "otziv_SED_NCPI_RB.pdf"
_A2_NAME = "contract.pdf"
_A1_BODY = "MARKER_A1_OTZIV_SED_NCPI_BODY"
_A2_BODY = "MARKER_A2_CONTRACT_BODY"
_SCRATCH_A2_MARKER = "P0E_SCRATCH_FOREIGN_UUID"


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

    def user_payload_ids(self, thread_id: str) -> list[tuple[UUID, ...]]:
        out: list[tuple[UUID, ...]] = []
        for turn in self._turns.get(thread_id, []):
            if turn.role != "user":
                continue
            out.append(parse_turn_attachment_ids(turn.payload))
        return out

    def mutate_first_user_payload(self, thread_id: str, attachment_ids: list[UUID]) -> None:
        for turn in self._turns.get(thread_id, []):
            if turn.role != "user":
                continue
            # DialogTurn is frozen — replace list entry.
            idx = self._turns[thread_id].index(turn)
            self._turns[thread_id][idx] = turn.model_copy(
                update={"payload": {"attachment_ids": [str(aid) for aid in attachment_ids]}}
            )
            return
        raise AssertionError(f"no user turn in {thread_id}")


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
        '"reasoning": "p0e knowledge"}'
    )


def _intent_format() -> str:
    return (
        '{"task_kind": "response_formatting", "requires_mcp": false, '
        '"candidate_capabilities": ["format"], "confidence": 0.92, '
        '"reasoning": "p0e format"}'
    )


def _ctx_new_topic(query: str) -> str:
    return (
        "{"
        f'"rewritten_query": "{query}", '
        '"continuation_kind": "new_topic", '
        '"confidence": 0.9, '
        '"refers_to_prior": false, '
        '"prior_assistant_excerpt": null, '
        '"reasoning": "p0e seed"'
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
        '"reasoning": "p0e file-bound format"'
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
        '"reasoning": "p0e file follow-up; ambiguity letter vs contract"'
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
    memory_port: InMemoryMemoryPort | None = None,
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


async def test_p0e_h5a_dialog_write_and_h6_pending_isolation() -> None:
    """H5a: T1/T2 payloads stay thread-local. H6: foreign pending does not select fence ids."""
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
            # H6 follow-up: file-bound format; pending will be poisoned to A2.
            _intent_format(),
            _ctx_format("покажи полный текст файла", prior=prior_excerpt),
        ],
    )
    captured = await _capture_states(intent)

    await intent.process(
        text="сводка",
        thread_id=_T1,
        task_id="p0e-t1-1",
        user_id=_USER,
        attachment_ids=[a1_id],
    )
    await intent.process(
        text="сводка",
        thread_id=_T2,
        task_id="p0e-t2-1",
        user_id=_USER,
        attachment_ids=[a2_id],
    )

    # H5a — dialog write integrity after seed.
    t1_payloads = dialog.user_payload_ids(_T1)
    t2_payloads = dialog.user_payload_ids(_T2)
    assert t1_payloads == [(a1_id,)], f"H5a T1 write polluted; payloads={t1_payloads!r}"
    assert t2_payloads == [(a2_id,)], f"H5a T2 write polluted; payloads={t2_payloads!r}"
    assert a2_id not in {aid for batch in t1_payloads for aid in batch}
    assert a1_id not in {aid for batch in t2_payloads for aid in batch}

    # H6 — poison T1 pending to A2; dialog prior still A1-only.
    await sessions.touch_session(
        thread_id=_T1,
        context_patch={PENDING_ATTACHMENT_IDS_KEY: serialize_pending_attachment_ids([a2_id])},
    )
    pending_before = await intent._pending_attachment_ids(thread_id=_T1)  # type: ignore[attr-defined]
    assert pending_before == [a2_id]

    await intent.process(
        text="покажи полный текст файла",
        thread_id=_T1,
        task_id="p0e-t1-2",
        user_id=_USER,
    )

    assert len(captured) == 3
    ctx = str(captured[2].get("untrusted_context") or "")
    refs = citation_refs_from_untrusted_context(ctx)
    assert _A1_NAME in ctx, f"H6: expected dialog-bound A1 fence; ctx={ctx!r}"
    assert _A2_NAME not in ctx, f"H6 CONFIRMED: pending A2 selected over dialog; ctx={ctx!r}"
    assert str(a2_id) not in ctx, f"H6: A2 uuid in fence via pending; ctx={ctx!r}"
    assert refs == (_A1_NAME,), f"H6 attachment_refs; refs={refs!r}"


async def test_p0e_h5b_polluted_dialog_prior_must_not_fence_foreign() -> None:
    """H5b regression (P0-A): T1 dialog payload with A2 UUID must not fence A2.

    Before fix: rehydrate → get_many(user_id) resolved cross-thread A2 into fence.
    After fix: get_many(..., thread_id=T1) skips A2; rehydrate soft-skips → no foreign fence.
    """
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
        ],
    )
    captured = await _capture_states(intent)

    await intent.process(
        text="сводка",
        thread_id=_T1,
        task_id="p0e-h5b-t1-1",
        user_id=_USER,
        attachment_ids=[a1_id],
    )
    await intent.process(
        text="сводка",
        thread_id=_T2,
        task_id="p0e-h5b-t2-1",
        user_id=_USER,
        attachment_ids=[a2_id],
    )

    # Simulate bad dialog write / cross-session id injection into T1 prior.
    dialog.mutate_first_user_payload(_T1, [a2_id])
    assert dialog.user_payload_ids(_T1)[0] == (a2_id,)

    await intent.process(
        text="покажи полный текст файла",
        thread_id=_T1,
        task_id="p0e-h5b-t1-2",
        user_id=_USER,
    )

    assert len(captured) == 3
    ctx = str(captured[2].get("untrusted_context") or "")
    refs = citation_refs_from_untrusted_context(ctx)

    assert _A2_NAME not in ctx, (
        f"H5b CONFIRMED: polluted dialog prior retargeted fence to A2; untrusted_context={ctx!r} refs={refs!r}"
    )
    assert str(a2_id) not in ctx, f"H5b: A2 uuid fenced from dialog; ctx={ctx!r}"
    assert _A2_BODY not in ctx, f"H5b: A2 body fenced from dialog; ctx={ctx!r}"
    assert _A1_NAME in ctx or refs == (), f"H5b: expected A1 retained or empty fence, got refs={refs!r} ctx={ctx!r}"


async def test_p0e_scratchpad_uuid_does_not_become_attachment_refs() -> None:
    """Scratchpad text with foreign UUID must not invent attachment_refs beyond fence.

    Isolates the claim that attachment_refs is assembled from scratchpad + fence.
    Dialog prior stays clean (A1 only).
    """
    parser = _FakeParser(ParsedDocument(pages=(ParsedPage(number=1, text=_A1_BODY),)))
    att_service, blob, _repo = _stack(parser=parser)
    a1_id = await _upload_ready(att_service, blob, parser, thread_id=_T1, filename=_A1_NAME, body=_A1_BODY)
    a2_id = await _upload_ready(att_service, blob, parser, thread_id=_T2, filename=_A2_NAME, body=_A2_BODY)

    memory = InMemoryMemoryPort()
    scratch = SessionScratchpadService(memory)
    await scratch.save(
        SessionScratchpad(
            thread_id=_T1,
            slots=(
                ScratchpadSlot(
                    key="foreign-hint",
                    text=(f"{_SCRATCH_A2_MARKER} покажи полный текст файла {_A2_NAME} attachment_id={a2_id}"),
                    kind="fact",
                ),
            ),
        )
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
            _ctx_answer("покажи полный текст файла", prior=prior_excerpt),
        ],
    )
    captured = await _capture_states(intent)

    await intent.process(
        text="сводка",
        thread_id=_T1,
        task_id="p0e-sc-t1-1",
        user_id=_USER,
        attachment_ids=[a1_id],
    )
    # Sanity: dialog write still A1-only before follow-up.
    assert dialog.user_payload_ids(_T1) == [(a1_id,)]

    await intent.process(
        text="покажи полный текст файла",
        thread_id=_T1,
        task_id="p0e-sc-t1-2",
        user_id=_USER,
    )

    assert len(captured) == 2
    turn2 = captured[1]
    ctx = str(turn2.get("untrusted_context") or "")
    refs = citation_refs_from_untrusted_context(ctx)
    recall = turn2.get("memory_recall")
    hints = "\n".join(str(getattr(hit, "text", "")) for hit in (getattr(recall, "hits", ()) or ()))

    # Scratchpad pollution present in recall (same thread — expected).
    assert _SCRATCH_A2_MARKER in hints or str(a2_id) in hints, f"setup: T1 scratchpad with A2 not recalled; hints={hints!r}"
    # attachment_refs / fence must still be A1-only (not assembled from scratchpad).
    assert _A2_NAME not in ctx, f"scratchpad→fence LEAK; ctx={ctx!r}"
    assert str(a2_id) not in ctx, f"scratchpad uuid→fence LEAK; ctx={ctx!r}"
    assert _A2_NAME not in refs, f"attachment_refs from scratchpad; refs={refs!r}"
    assert _A1_NAME in ctx, f"expected A1 fence; ctx={ctx!r}"
    assert refs == (_A1_NAME,), f"expected A1-only attachment_refs; refs={refs!r}"
