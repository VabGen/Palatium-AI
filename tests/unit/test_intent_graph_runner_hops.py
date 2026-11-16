"""SSE ``hop`` = СТАРТ узла графа, а не его финиш.

Индикатор ожидания в виджете называет шаг, который выполняется СЕЙЧАС
(`stream_mode="tasks"`): событие финиша пришло бы уже после работы узла и
откатило бы фазу назад — тест держит это различие.
"""

from __future__ import annotations

from typing import Any

import pytest

from palatium_ai.application.services.intent_graph_runner import IntentGraphRunner


async def _events(item: object) -> list[dict[str, Any]]:
    return [
        event
        async for event in IntentGraphRunner._events_from_astream_item(
            item,
            task_id="task-1",
            thread_id="thread-1",
        )
    ]


@pytest.mark.asyncio()
async def test_task_start_becomes_a_hop() -> None:
    events = await _events(
        (
            "tasks",
            {
                "id": "run-a",
                "name": "researcher",
                "input": {},
                "triggers": ["start:supervisor"],
            },
        )
    )

    assert events == [
        {
            "event": "hop",
            "node": "researcher",
            "task_id": "task-1",
            "thread_id": "thread-1",
        }
    ]


@pytest.mark.asyncio()
async def test_task_result_is_not_a_hop() -> None:
    events = await _events(
        (
            "tasks",
            {
                "id": "run-a",
                "name": "researcher",
                "error": None,
                "interrupts": [],
                "result": {"research": None},
            },
        )
    )

    assert events == []


@pytest.mark.asyncio()
async def test_values_item_still_carries_rolling_state() -> None:
    events = await _events(("values", {"trace_id": "tr-1"}))

    assert events == [
        {
            "event": "_values",
            "state": {"trace_id": "tr-1"},
            "task_id": "task-1",
            "thread_id": "thread-1",
        }
    ]
