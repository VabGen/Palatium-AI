# tests/integration/test_memory_mutation_turn.py

"""E2E turn: «запомни …» / «забудь …» → Intent gate → HITL card → approve → MCP write.

Covers E2E-01/03 at the graph boundary, not the gate in isolation: the turn must end
on the deterministic mutation node (no worker, no formatter, no success prose), the
approval card must survive ``finalize_formatted_state``, and the mutation must not
reach ``memory.entries`` before the human approves.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.application.services.memory_forget_service import MEM_FORGET_TASK_PREFIX
from palatium_ai.application.services.memory_mutation import MemoryMutationGate
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.application.services.memory_save_service import MEM_SAVE_TASK_PREFIX
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.domain.hitl.cards import HITLResolveRequest
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from tests.conftest import (
    FakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_continuation_agent,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_intent_stack,
    make_memory_hitl_stack,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

if TYPE_CHECKING:
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.memory_forget_service import MemoryForgetService
    from palatium_ai.application.services.memory_save_service import MemorySaveService
    from palatium_ai.domain.agents.formatter import FormatterTaskResult
    from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort

_USER = "user-mem-turn"
_ORG = "org-mem-turn"
_THREAD = "thread-mem-turn"

_MUTATION_SAVE_JSON = json.dumps(
    {
        "task_kind": "tool_execution",
        "requires_mcp": True,
        "candidate_capabilities": [],
        "memory_mutation": "save",
        "memory_text": "порт базы данных 5433",
        "memory_key": "db_port",
        "confidence": 0.94,
        "reasoning": "explicit memory write",
    }
)
_MUTATION_FORGET_JSON = json.dumps(
    {
        "task_kind": "tool_execution",
        "requires_mcp": True,
        "candidate_capabilities": [],
        "memory_mutation": "forget",
        "memory_text": "порт базы данных",
        "confidence": 0.92,
        "reasoning": "explicit memory deletion",
    }
)
_MUTATION_FORGET_MISS_JSON = json.dumps(
    {
        "task_kind": "tool_execution",
        "requires_mcp": True,
        "candidate_capabilities": [],
        "memory_mutation": "forget",
        "memory_text": "лунный грунт",
        "confidence": 0.9,
        "reasoning": "explicit memory deletion",
    }
)


class _FakeSessionService:
    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None

    async def get_session(self, **_kwargs: object) -> None:
        return None


def _formatter_json(title: str) -> str:
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


def _action_request(card: object, *, action_id: str, idempotency_key: str) -> HITLResolveRequest:
    option = next(opt for opt in card.options if opt.action_id == action_id)  # type: ignore[attr-defined]
    return HITLResolveRequest(
        action_id=action_id,
        action_token=option.action_token,
        idempotency_key=idempotency_key,
    )


@dataclass(frozen=True)
class _MutationTurnStack:
    """Everything a mutation turn test needs, including the LLMs that must stay idle."""

    service: IntentService
    gate: MemoryMutationGate
    port: InMemoryMemoryPort
    save: MemorySaveService
    forget: MemoryForgetService
    hitl: HitlService
    researcher_llm: FakeLLMPort
    formatter_llm: FakeLLMPort


def _mutation_service(*, intent_json: str) -> _MutationTurnStack:
    """Graph with the real mutation gate + the hitl/memory stack behind it."""
    save, forget, port, hitl, _handler = make_memory_hitl_stack()
    gate = MemoryMutationGate(save_service=save, forget_service=forget, memory_port=port)  # type: ignore[arg-type]
    harness, intent_agent = make_intent_stack(FakeLLMPort(intent_json))
    unused_researcher = FakeLLMPort('{"summary": "must-not-run", "confidence": 0.1, "sources_used": []}')
    unused_formatter = FakeLLMPort(_formatter_json("must-not-run"))
    graph = build_agent_graph(
        GraphAgents(
            continuation_agent=make_continuation_agent(harness=harness),
            intent_agent=intent_agent,
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=make_researcher_agent(unused_researcher, harness=harness),
            coder_agent=make_coder_agent(harness=harness),
            analyst_agent=make_analyst_agent(harness=harness),
            critic_agent=make_critic_agent(FakeLLMPort("must-not-run")),
            formatter_agent=make_formatter_agent(unused_formatter),
            memory_mutation_gate=gate,
        ),
        harness=harness,
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=hitl,  # type: ignore[arg-type]
    )
    return _MutationTurnStack(
        service=service,
        gate=gate,
        port=port,  # type: ignore[arg-type]
        save=save,  # type: ignore[arg-type]
        forget=forget,  # type: ignore[arg-type]
        hitl=hitl,  # type: ignore[arg-type]
        researcher_llm=unused_researcher,
        formatter_llm=unused_formatter,
    )


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_save_turn_stages_card_then_writes_only_after_approval() -> None:
    stack = _mutation_service(intent_json=_MUTATION_SAVE_JSON)

    result = await stack.service.process(
        text="Запомни, порт базы данных 5433",
        thread_id=_THREAD,
        task_id="task-mem-save",
        user_id=_USER,
        org_id=_ORG,
    )

    # The turn ends on the mutation node: a card, not a success claim (030.8/020).
    assert len(result.hitl_cards) == 1
    card = result.hitl_cards[0]
    assert card.task_id.startswith(MEM_SAVE_TASK_PREFIX)
    assert result.requires_review is True
    assert result.status == "partial"
    assert result.output is not None
    assert "порт базы данных 5433" in result.output.plain_text()
    assert len(stack.researcher_llm.calls) == 0
    assert len(stack.formatter_llm.calls) == 0
    assert await stack.port.get(namespace=user_namespace(_USER), key="db_port") is None

    facade = HitlRespondFacade(
        hitl_service=stack.hitl,
        intent_service=AsyncMock(),
        memory_save_service=stack.save,
        memory_forget_service=stack.forget,
    )
    outcome = await facade.respond(
        card.card_id,
        _action_request(card, action_id="approve", idempotency_key="mem-turn-save-approve"),
        actor_subject=_USER,
        actor_org_id=_ORG,
        is_admin=False,
    )
    assert outcome.resumed is not None
    assert outcome.resumed.status == "success"

    stored = await stack.port.get(namespace=user_namespace(_USER), key="db_port")
    assert stored is not None
    assert stored["text"] == "порт базы данных 5433"

    # E2E-03 acceptance: an approved explicit write is durable memory — a *new* thread
    # recalls the value, while extract-inferred facts stay thread-scoped (P0-B).
    new_thread = await recall_for_thread(stack.port, thread_id="thread-other", user_id=_USER, query="порт базы данных")
    assert any("5433" in hit.text for hit in new_thread.hits)


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_forget_turn_deletes_only_after_approval() -> None:
    stack = _mutation_service(intent_json=_MUTATION_FORGET_JSON)
    await stack.port.put(
        namespace=user_namespace(_USER),
        key="db_port",
        value={"text": "порт базы данных 5433", "user_id": _USER, "confidence": 1.0},
    )

    result = await stack.service.process(
        text="Забудь про порт базы данных",
        thread_id=_THREAD,
        task_id="task-mem-forget",
        user_id=_USER,
        org_id=_ORG,
    )

    assert len(result.hitl_cards) == 1
    card = result.hitl_cards[0]
    assert card.task_id.startswith(MEM_FORGET_TASK_PREFIX)
    assert result.output is not None
    assert "порт базы данных 5433" in result.output.plain_text()
    # Nothing is deleted before the human approves the card.
    assert await stack.port.get(namespace=user_namespace(_USER), key="db_port") is not None

    facade = HitlRespondFacade(
        hitl_service=stack.hitl,
        intent_service=AsyncMock(),
        memory_save_service=stack.save,
        memory_forget_service=stack.forget,
    )
    outcome = await facade.respond(
        card.card_id,
        _action_request(card, action_id="approve", idempotency_key="mem-turn-forget-approve"),
        actor_subject=_USER,
        actor_org_id=_ORG,
        is_admin=False,
    )
    assert outcome.resumed is not None
    assert outcome.resumed.status == "success"

    assert await stack.port.get(namespace=user_namespace(_USER), key="db_port") is None
    hits = await stack.port.search(namespace=user_namespace(_USER), query="порт базы данных", limit=5)
    assert hits == []


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_forget_turn_clears_the_thread_scratchpad_pin() -> None:
    """R2.4: a warmed thread must not keep answering a fact whose forget was approved."""
    stack = _mutation_service(intent_json=_MUTATION_FORGET_JSON)
    scratchpad = SessionScratchpadService(stack.port)
    await scratchpad.save(
        SessionScratchpad(
            thread_id=_THREAD,
            slots=(ScratchpadSlot(key="u:port", text="Запомни, порт базы данных 5433"),),
        )
    )
    await stack.port.put(
        namespace=user_namespace(_USER),
        key="db_port",
        value={"text": "порт базы данных 5433", "user_id": _USER, "confidence": 1.0},
    )
    warmed = await scratchpad.load(thread_id=_THREAD)
    before = await recall_for_thread(stack.port, thread_id=_THREAD, query="на каком порту база", scratchpad=warmed)
    assert any("5433" in hit.text for hit in before.hits), "scratchpad pin must be visible before forget"

    result = await stack.service.process(
        text="Забудь про порт базы данных",
        thread_id=_THREAD,
        task_id="task-mem-forget-pin",
        user_id=_USER,
        org_id=_ORG,
    )
    card = result.hitl_cards[0]
    facade = HitlRespondFacade(
        hitl_service=stack.hitl,
        intent_service=AsyncMock(),
        memory_save_service=stack.save,
        memory_forget_service=stack.forget,
    )
    outcome = await facade.respond(
        card.card_id,
        _action_request(card, action_id="approve", idempotency_key="mem-turn-forget-pin"),
        actor_subject=_USER,
        actor_org_id=_ORG,
        is_admin=False,
    )
    assert outcome.resumed is not None
    assert outcome.resumed.status == "success"

    after_pad = await scratchpad.load(thread_id=_THREAD)
    assert not any("5433" in slot.text for slot in after_pad.slots), "approved forget must clear the pin"
    after = await recall_for_thread(stack.port, thread_id=_THREAD, query="на каком порту база", scratchpad=after_pad)
    assert not any("5433" in hit.text for hit in after.hits)


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_save_turn_supersedes_the_stale_thread_pin() -> None:
    """E2E-03 class: the approved write must win over a pre-write scratchpad pin."""
    stack = _mutation_service(intent_json=_MUTATION_SAVE_JSON)
    scratchpad = SessionScratchpadService(stack.port)
    await scratchpad.save(
        SessionScratchpad(
            thread_id=_THREAD,
            slots=(ScratchpadSlot(key="u:port", text="Запомни, порт базы данных 5432"),),
        )
    )

    result = await stack.service.process(
        text="Запомни, порт базы данных 5433",
        thread_id=_THREAD,
        task_id="task-mem-save-supersede",
        user_id=_USER,
        org_id=_ORG,
    )
    card = result.hitl_cards[0]
    facade = HitlRespondFacade(
        hitl_service=stack.hitl,
        intent_service=AsyncMock(),
        memory_save_service=stack.save,
        memory_forget_service=stack.forget,
    )
    await facade.respond(
        card.card_id,
        _action_request(card, action_id="approve", idempotency_key="mem-turn-save-supersede"),
        actor_subject=_USER,
        actor_org_id=_ORG,
        is_admin=False,
    )

    pad = await scratchpad.load(thread_id=_THREAD)
    assert not any("5432" in slot.text for slot in pad.slots), "stale pin must be superseded"
    recall = await recall_for_thread(stack.port, thread_id=_THREAD, user_id=_USER, query="порт базы данных", scratchpad=pad)
    assert any("5433" in hit.text for hit in recall.hits)
    assert not any("5432" in hit.text for hit in recall.hits)


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_forget_turn_without_match_is_honest_and_mints_no_card() -> None:
    stack = _mutation_service(intent_json=_MUTATION_FORGET_MISS_JSON)

    result = await stack.service.process(
        text="Забудь про лунный грунт",
        thread_id=_THREAD,
        task_id="task-mem-forget-miss",
        user_id=_USER,
        org_id=_ORG,
    )

    assert result.hitl_cards == ()
    assert result.status == "success"
    assert result.output is not None
    assert "ничего не нашлось" in result.output.plain_text().lower()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_rejected_save_card_leaves_memory_untouched() -> None:
    stack = _mutation_service(intent_json=_MUTATION_SAVE_JSON)
    result: FormatterTaskResult = await stack.service.process(
        text="Запомни, порт базы данных 5433",
        thread_id=_THREAD,
        task_id="task-mem-save-reject",
        user_id=_USER,
        org_id=_ORG,
    )
    card = result.hitl_cards[0]

    facade = HitlRespondFacade(
        hitl_service=stack.hitl,
        intent_service=AsyncMock(),
        memory_save_service=stack.save,
        memory_forget_service=stack.forget,
    )
    await facade.respond(
        card.card_id,
        _action_request(card, action_id="reject", idempotency_key="mem-turn-save-reject"),
        actor_subject=_USER,
        actor_org_id=_ORG,
        is_admin=False,
    )

    assert await stack.port.get(namespace=user_namespace(_USER), key="db_port") is None
