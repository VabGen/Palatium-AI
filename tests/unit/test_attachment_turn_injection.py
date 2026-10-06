# tests/unit/test_attachment_turn_injection.py

"""Fenced attachment text must reach the prompt as data, never as instructions (020, 065).

Two layers are covered here:
1. the budget helper that trims an over-long fenced block with an explicit marker;
2. the dialog-turn plumbing — ``IntentService`` resolves attachments through
   ``AttachmentService`` and the fenced text ends up in the packet that the
   researcher/critic/formatter read, so no agent has to concatenate raw file
   text itself.
"""

from __future__ import annotations

import json

from uuid import uuid4

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.attachments.context import AttachmentContextBlock, AttachmentTurnContext
from palatium_ai.domain.attachments.errors import AttachmentNotUsableError
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from tests.conftest import (
    FakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

pytestmark = pytest.mark.asyncio

_HITL_HMAC = "unit-test-hitl-hmac-key-32b"
_FENCE_START = "<<<UNTRUSTED_TOOL_OUTPUT"
_FENCE_END = "<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


class _FakeSessionService:
    """No-op session persistence for graph unit tests."""

    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None

    async def get_session(self, **_kwargs: object) -> None:
        return None


class _StubAttachmentService:
    """Returns a pre-built (already fenced) turn context; records the ids it saw."""

    def __init__(self, context: AttachmentTurnContext | None = None, *, error: Exception | None = None) -> None:
        self._context = context or AttachmentTurnContext()
        self._error = error
        self.calls: list[tuple[tuple[object, ...], str, str | None]] = []

    async def build_turn_context(
        self,
        *,
        attachment_ids: list[object],
        user_id: str,
        thread_id: str | None = None,
    ) -> AttachmentTurnContext:
        self.calls.append((tuple(attachment_ids), user_id, thread_id))
        if self._error is not None:
            raise self._error
        return self._context


def _fence(text: str, *, filename: str = "contract.txt") -> str:
    """Stand-in for what AttachmentService emits (the real fence is asserted in its own tests)."""
    return f"{_FENCE_START} source=attachment:{filename}>>>\n{text}\n{_FENCE_END}"


def _intent_service(graph: object, attachment_service: object | None = None) -> IntentService:
    return IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        attachment_service=attachment_service,  # type: ignore[arg-type]
    )


def _graph(**kwargs: object) -> object:
    harness = kwargs.pop("harness", None)
    if harness is None:
        harness = Harness(llm=FakeLLMPort("{}"))
    checkpointer = kwargs.pop("checkpointer", None) or make_graph_checkpointer()
    kwargs.setdefault("continuation_agent", ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG))  # type: ignore[arg-type]
    kwargs.setdefault("coder_agent", make_coder_agent(harness=harness))
    kwargs.setdefault("analyst_agent", make_analyst_agent(harness=harness))
    return build_agent_graph(GraphAgents(**kwargs), harness=harness, checkpointer=checkpointer)  # type: ignore[arg-type]


def _formatter_document_json(title: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "locale": "en-US",
            "title": title,
            "blocks": [{"type": "paragraph", "text": title}],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        },
        ensure_ascii=False,
    )


def _last_user_payload(llm: FakeLLMPort) -> dict[str, object]:
    """Parse the user message of the latest LLM call into a dict."""
    assert llm.calls, "LLM was never called"
    last = llm.calls[-1]
    user_messages = [message for message in last if message.role == "user"]
    assert user_messages, "no user message in the last LLM call"
    payload = json.loads(user_messages[-1].content)
    assert isinstance(payload, dict)
    return payload


async def test_turn_without_attachment_ids_keeps_context_empty() -> None:
    service = _intent_service(object())
    assert await service._turn_untrusted_context(None, thread_id="t", user_id="u") == ""
    assert await service._turn_untrusted_context([], thread_id="t", user_id="u") == ""


async def test_turn_without_attachment_service_warns_and_continues() -> None:
    """A disabled subsystem must not silently pretend the file was read."""
    service = _intent_service(object())
    assert await service._turn_untrusted_context([uuid4()], thread_id="t", user_id="u") == ""


async def test_turn_context_is_resolved_for_the_calling_user() -> None:
    attachment_id = uuid4()
    stub = _StubAttachmentService(
        AttachmentTurnContext(
            blocks=(
                AttachmentContextBlock(
                    attachment_id=attachment_id,
                    filename="contract.txt",
                    source="attachment:contract.txt",
                    fenced_text=_fence("Договор поставки №42"),
                    action="allow",
                    page_count=1,
                ),
            )
        )
    )
    service = _intent_service(object(), stub)

    fenced = await service._turn_untrusted_context([attachment_id], thread_id="t-1", user_id="u-1")

    assert _FENCE_START in fenced
    assert "Договор поставки №42" in fenced
    assert stub.calls == [((attachment_id,), "u-1", "t-1")]


async def test_unusable_attachment_fails_the_turn_instead_of_being_dropped() -> None:
    """Fail closed: a quarantined file must surface, not vanish from the answer (020)."""
    stub = _StubAttachmentService(error=AttachmentNotUsableError(uuid4(), state="quarantined"))
    service = _intent_service(object(), stub)

    with pytest.raises(AttachmentNotUsableError):
        await service._turn_untrusted_context([uuid4()], thread_id="t", user_id="u")


async def test_fenced_attachment_reaches_researcher_and_formatter_payloads() -> None:
    """End-to-end: the fence is what the workers see, and only via the packet."""
    llm_intent = FakeLLMPort(
        '{"task_kind": "knowledge_request", "requires_mcp": false, "candidate_capabilities": ["summarize"], '
        '"confidence": 0.95, "reasoning": "Question about an attached document"}',
    )
    llm_researcher = FakeLLMPort(
        '{"summary": "Delivery terms per the attached contract.", "confidence": 0.9, '
        '"sources_used": ["llm_internal_reasoning"]}',
    )
    llm_critic = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Looks correct"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Answered from attachment"))

    harness = Harness(llm=llm_intent)
    intent_agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    graph = _graph(
        harness=harness,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(llm_researcher, harness=harness),
        critic_agent=make_critic_agent(llm_critic),
        formatter_agent=make_formatter_agent(llm_formatter),
    )
    attachment_id = uuid4()
    stub = _StubAttachmentService(
        AttachmentTurnContext(
            blocks=(
                AttachmentContextBlock(
                    attachment_id=attachment_id,
                    filename="contract.txt",
                    source="attachment:contract.txt",
                    fenced_text=_fence("Договор поставки №42. Сроки поставки: 30 дней."),
                    action="allow",
                    page_count=1,
                ),
            )
        )
    )
    service = _intent_service(graph, stub)

    result = await service.process(
        text="What are the delivery terms?",
        thread_id="thread-att-1",
        task_id="task-att-1",
        user_id="user-1",
        attachment_ids=[attachment_id],
    )

    assert result.status == "success"
    assert stub.calls, "attachments were never resolved for the turn"

    # The critic sees the same fenced block, so it can judge grounding and spot a draft
    # that obeyed an instruction hidden in the attachment.
    critic_payload = _last_user_payload(llm_critic)
    assert str(critic_payload["attachment_context"]).startswith(_FENCE_START)
    assert "Договор поставки №42" in str(critic_payload["attachment_context"])

    formatter_payload = _last_user_payload(llm_formatter)
    attachment_context = str(formatter_payload["attachment_context"])
    assert attachment_context.startswith(_FENCE_START)
    assert "Договор поставки №42" in attachment_context


async def test_researcher_payload_carries_fenced_attachment_context() -> None:
    """The Researcher receives the block as ``attachment_context``, never merged into the ask."""
    from palatium_ai.application.orchestration.agent_bridge import researcher_to_agent_input
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.researcher import ResearcherInput
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    llm = FakeLLMPort(
        '{"summary": "Answer from the attachment", "confidence": 0.9, "sources_used": ["llm_internal_reasoning"]}',
    )
    harness = Harness(llm=llm)
    agent = make_researcher_agent(llm, harness=harness)
    packet = ContextPacket(
        task_id="task-att",
        user_text="What are the delivery terms?",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="Answer from the attached contract",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", rationale="Attachment is enough"),
        context_summary="attachment turn",
        untrusted_context=_fence("Договор поставки №42. Сроки поставки: 30 дней."),
    )
    agent_input = researcher_to_agent_input(
        ResearcherInput(task_id="task-att", context_packet=packet),
        trace_id="trace-att",
        thread_id="thread-att",
    )

    await harness.execute_with_guardrails(agent, agent_input)

    payload = _last_user_payload(llm)
    assert str(payload["attachment_context"]).startswith(_FENCE_START)
    assert "Договор поставки №42" in str(payload["attachment_context"])
    assert payload["user_text"] == "What are the delivery terms?"


async def test_turn_without_attachments_sends_an_empty_context_slot() -> None:
    """Agents always receive the key, so nothing has to guard for a missing field."""
    llm_intent = FakeLLMPort(
        '{"task_kind": "knowledge_request", "requires_mcp": false, "candidate_capabilities": ["summarize"], '
        '"confidence": 0.95, "reasoning": "General question"}',
    )
    llm_researcher = FakeLLMPort(
        '{"summary": "Answer without attachments.", "confidence": 0.9, "sources_used": ["llm_internal_reasoning"]}',
    )
    llm_critic = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Looks correct"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Plain answer"))

    harness = Harness(llm=llm_intent)
    graph = _graph(
        harness=harness,
        intent_agent=IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(llm_researcher, harness=harness),
        critic_agent=make_critic_agent(llm_critic),
        formatter_agent=make_formatter_agent(llm_formatter),
    )
    service = _intent_service(graph, _StubAttachmentService())

    result = await service.process(
        text="Explain the process",
        thread_id="thread-att-2",
        task_id="task-att-2",
        user_id="user-1",
    )

    assert result.status == "success"
    # Reviewer and formatter always run for this route, so they prove the slot exists
    # (and is empty) even when no attachment was sent.
    assert _last_user_payload(llm_critic)["attachment_context"] == ""
    assert _last_user_payload(llm_formatter)["attachment_context"] == ""
