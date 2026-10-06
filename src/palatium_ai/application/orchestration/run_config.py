# src/palatium_ai/application/orchestration/run_config.py

"""LangGraph invoke config — conversation thread vs per-task working memory.

Dialog continuity lives in DialogTurnStore / MemoryPort (Postgres), not in the
checkpointer. Checkpointer scopes *within-turn* working state (HITL interrupt/resume).

Using ``thread_id`` alone would leak prior-turn channels (e.g. stale ``execution``)
into the next turn when Researcher is skipped.

**Do not** put the turn id in ``configurable.checkpoint_ns``. In LangGraph,
a non-empty ``checkpoint_ns`` without an injected checkpointer is treated as a
*subgraph* path by ``get_state`` / ``aget_state`` (``Subgraph … not found``).
Turn isolation therefore uses a composite checkpointer ``thread_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

# Safety bound for LangGraph supersteps. Current graph is a DAG (~7 nodes);
# keep headroom for interrupt/resume, fail closed if cycles are introduced later.
GRAPH_RECURSION_LIMIT = 32
_CHECKPOINT_THREAD_SEP = ":"

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


def checkpoint_thread_id(*, thread_id: str, task_id: str) -> str:
    """Stable LangGraph checkpointer key for one conversation turn."""
    return f"{thread_id}{_CHECKPOINT_THREAD_SEP}{task_id}"


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
                "thread_id": checkpoint_thread_id(thread_id=thread_id, task_id=task_id),
            },
        },
    )
