"""Smoke: checkpointer factory + checkpoint_ns isolation."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from palatium_ai.application.orchestration.run_config import build_graph_run_config
from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.memory.checkpointer import (
    create_checkpointer,
    ensure_psycopg_compatible_loop,
)


class _CounterState(TypedDict):
    n: int


async def _increment(state: _CounterState) -> _CounterState:
    return {"n": state["n"] + 1}


async def main() -> None:
    """Verify saver type and per-task checkpoint namespace isolation."""
    ensure_psycopg_compatible_loop()
    handle = await create_checkpointer(get_settings())
    saver_name = type(handle.saver).__name__
    print(saver_name)

    graph = StateGraph(_CounterState)
    graph.add_node("increment", _increment)
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    app = graph.compile(checkpointer=handle.saver)

    thread_id = "smoke-thread"
    first = await app.ainvoke(
        {"n": 0},
        config=build_graph_run_config(thread_id=thread_id, task_id="task-a"),
    )
    second = await app.ainvoke(
        {"n": 0},
        config=build_graph_run_config(thread_id=thread_id, task_id="task-b"),
    )
    if first["n"] != 1:
        raise SystemExit(f"expected task-a n=1, got {first['n']}")
    if second["n"] != 1:
        raise SystemExit(f"expected fresh task-b n=1 (not inherited), got {second['n']}")
    print("checkpoint_ns_isolation=ok")

    if handle.aclose is not None:
        with contextlib.suppress(Exception):
            await handle.aclose()


if __name__ == "__main__":
    ensure_psycopg_compatible_loop()
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"smoke_failed: {exc}", file=sys.stderr)
        raise
