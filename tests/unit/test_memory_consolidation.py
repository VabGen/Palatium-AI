"""MemoryPort + sleep-time consolidation unit tests."""

from __future__ import annotations

import asyncio
import json

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import FakeLLMPort, make_platform_mcp_registry


def _consolidation_service(
    *,
    harness: Harness,
    keeper: MemoryKeeperAgent,
    port: InMemoryMemoryPort,
    dialog: _FakeDialogTurnStore,
) -> MemoryConsolidationService:
    registry = make_platform_mcp_registry(memory_port=port)
    persistence = MemoryFactPersistenceService(registry)
    return MemoryConsolidationService(
        harness=harness,
        memory_keeper=keeper,
        memory_port=port,
        memory_persistence=persistence,
        dialog_turn_store=dialog,  # type: ignore[arg-type]
    )


class _FakeDialogTurnStore:
    def __init__(self, excerpt_turns: list[tuple[str, str]]) -> None:
        self._turns = excerpt_turns

    async def append_turn(self, **_kwargs: object) -> DialogTurn:
        raise NotImplementedError

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        turns = tuple(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role=role,  # type: ignore[arg-type]
                content=content,
                seq=idx,
                created_at=datetime.now(UTC),
            )
            for idx, (role, content) in enumerate(self._turns[:limit])
        )
        return DialogTurnWindow(thread_id=thread_id, turns=turns, limit=limit)


@pytest.mark.asyncio
async def test_in_memory_port_put_get_search() -> None:
    port = InMemoryMemoryPort()
    ns = thread_namespace("t1")
    await port.put(namespace=ns, key="k1", value={"text": "предпочитает таблицы", "kind": "preference"})
    assert await port.get(namespace=ns, key="k1") is not None
    hits = await port.search(namespace=ns, query="таблицы", limit=4)
    assert hits
    assert "таблицы" in str(hits[0]["text"])


@pytest.mark.asyncio
async def test_sleep_time_consolidation_stores_add_only_facts() -> None:
    port = InMemoryMemoryPort()
    payload = {
        "facts": [
            {
                "text": "User prefers meeting agendas as tables",
                "kind": "preference",
                "confidence": 0.9,
                "key_hint": "pref-tables",
            }
        ],
        "reasoning": "stable preference",
    }
    harness = Harness(llm=FakeLLMPort(json.dumps(payload)))
    keeper = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    dialog = _FakeDialogTurnStore(
        [
            ("user", "Составь план встречи"),
            ("assistant", "1. Цель 2. Повестка"),
            ("user", "Дай в виде таблицы"),
        ]
    )
    service = _consolidation_service(harness=harness, keeper=keeper, port=port, dialog=dialog)
    worker = asyncio.create_task(service.run_worker())
    assert service.enqueue(thread_id="thread-a", task_id="task-1", user_id="user-a")
    await asyncio.sleep(0.05)
    await service.stop()
    await worker

    hits = await port.search(namespace=user_namespace("user-a"), query="tables meeting", limit=5)
    assert hits
    assert hits[0]["kind"] == "preference"


@pytest.mark.asyncio
async def test_sleep_time_routes_preference_user_and_entity_org() -> None:
    port = InMemoryMemoryPort()
    payload = {
        "facts": [
            {
                "text": "User prefers tables for agendas",
                "kind": "preference",
                "confidence": 0.91,
                "key_hint": "pref-tables",
            },
            {
                "text": "Acme legal contact is Ivanova",
                "kind": "entity",
                "confidence": 0.88,
                "key_hint": "acme-legal",
            },
            {
                "text": "Meeting scheduled for Friday",
                "kind": "fact",
                "confidence": 0.8,
                "key_hint": "meeting-friday",
            },
        ],
        "reasoning": "mixed durable items",
    }
    harness = Harness(llm=FakeLLMPort(json.dumps(payload)))
    keeper = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    dialog = _FakeDialogTurnStore(
        [
            ("user", "Запомни: планы таблицей, контакт Acme — Иванова"),
            ("assistant", "Сохранил предпочтение и контакт."),
        ]
    )
    service = _consolidation_service(harness=harness, keeper=keeper, port=port, dialog=dialog)
    worker = asyncio.create_task(service.run_worker())
    assert service.enqueue(
        thread_id="thread-b",
        task_id="task-2",
        user_id="user-42",
        org_id="org-acme",
    )
    await asyncio.sleep(0.05)
    await service.stop()
    await worker

    user_hits = await port.search(namespace=user_namespace("user-42"), query="tables", limit=4)
    org_hits = await port.search(namespace=org_namespace("org-acme"), query="Ivanova", limit=4)
    thread_hits = await port.search(namespace=thread_namespace("thread-b"), query="Friday", limit=4)
    assert user_hits and user_hits[0]["kind"] == "preference"
    assert org_hits and org_hits[0]["kind"] == "entity"
    assert thread_hits and thread_hits[0]["kind"] == "fact"
