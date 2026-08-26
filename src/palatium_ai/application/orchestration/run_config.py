# src/palatium_ai/application/orchestration/run_config.py

"""LangGraph invoke config — conversation thread vs per-task working memory.

Dialog continuity lives in DialogTurnStore / MemoryPort (Postgres), not in the
checkpointer. Checkpointer scopes *within-turn* working state (HITL interrupt/resume).

Using ``thread_id`` alone would leak prior-turn channels (e.g. stale ``execution``)
into the next turn when Researcher is skipped. Using ``thread_id:task_id`` as the
thread key fragments conversation identity. Split:

- ``configurable.thread_id`` = conversation id (API thread_id)
- ``configurable.checkpoint_ns`` = task id (isolates turn working memory)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

# Safety bound for LangGraph supersteps. Current graph is a DAG (~7 nodes);
# keep headroom for interrupt/resume, fail closed if cycles are introduced later.
GRAPH_RECURSION_LIMIT = 32

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


def build_graph_run_config(*, thread_id: str, task_id: str) -> RunnableConfig:
    """Build LangGraph runnable config for one turn."""
    if not thread_id.strip():
        raise ValueError("thread_id must be non-empty")
    if not task_id.strip():
        raise ValueError("task_id must be non-empty")
    return cast(
        "RunnableConfig",
        {
            "recursion_limit": GRAPH_RECURSION_LIMIT,
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": task_id,
            },
        },
    )
