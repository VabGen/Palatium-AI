#!/usr/bin/env python
"""Multi-worker bake-off for LangGraph AsyncPostgresSaver.

Simulates two API workers that each open their own checkpointer pool,
write a checkpoint for the same thread_id, then read it back from the
other worker's saver.

LangGraph orders latest by checkpoint_id DESC and expects time-ordered
uuid6 ids (not uuid4).

Usage:
  poetry run python scripts/bakeoff_checkpointer_workers.py

Requires LANGGRAPH_CHECKPOINT_POSTGRES=true and reachable Postgres.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.base.id import uuid6

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.memory.checkpointer import (
    create_checkpointer,
    ensure_psycopg_compatible_loop,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata


def _minimal_checkpoint(*, step: int, payload: str) -> Checkpoint:
    """Build a tiny checkpoint blob with time-ordered uuid6 id."""
    return cast(
        "Checkpoint",
        {
            "v": 1,
            "id": str(uuid6(clock_seq=step)),
            "ts": datetime.now(UTC).isoformat(),
            "channel_values": {"payload": payload, "step": step},
            "channel_versions": {"payload": step, "step": step},
            "versions_seen": {},
            "pending_sends": [],
        },
    )


async def _worker_write(*, label: str, thread_id: str, step: int, payload: str) -> str:
    handle = await create_checkpointer(get_settings())
    saver = handle.saver
    base: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    existing = await saver.aget_tuple(base)
    config: RunnableConfig = existing.config if existing is not None else base
    meta = cast("CheckpointMetadata", {"source": "bakeoff", "step": step, "writes": {}})
    # Brief sleep so uuid6 timestamps differ across workers.
    await asyncio.sleep(0.02)
    saved = await saver.aput(
        config,
        _minimal_checkpoint(step=step, payload=payload),
        meta,
        {},
    )
    checkpoint_id = str(saved["configurable"]["checkpoint_id"])
    own = await saver.aget_tuple(base)
    own_values: dict[str, Any] = {}
    if own is not None:
        channel_values = own.checkpoint.get("channel_values", {})
        if isinstance(channel_values, dict):
            own_values = channel_values
    print(f"[{label}] wrote step={step} checkpoint_id={checkpoint_id} own_read={own_values}")
    if handle.aclose is not None:
        with contextlib.suppress(Exception):
            await handle.aclose()
    return checkpoint_id


async def _worker_read(*, label: str, thread_id: str) -> dict[str, object] | None:
    handle = await create_checkpointer(get_settings())
    saver = handle.saver
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    tuple_ = await saver.aget_tuple(config)
    if handle.aclose is not None:
        with contextlib.suppress(Exception):
            await handle.aclose()
    if tuple_ is None:
        print(f"[{label}] read: <empty>")
        return None
    values = tuple_.checkpoint.get("channel_values", {})
    print(f"[{label}] read: {values}")
    return dict(values) if isinstance(values, dict) else {"raw": values}


async def main() -> int:
    """Two sequential workers sharing Postgres checkpointer state."""
    ensure_psycopg_compatible_loop()
    settings = get_settings()
    if not settings.memory.use_postgres_checkpointer:
        print("LANGGRAPH_CHECKPOINT_POSTGRES is false — enable it for bake-off", file=sys.stderr)
        return 2

    thread_id = f"bakeoff-{uuid.uuid4()}"
    print(f"thread_id={thread_id}")

    await _worker_write(label="worker-A", thread_id=thread_id, step=1, payload="from-A")
    values_b = await _worker_read(label="worker-B", thread_id=thread_id)
    if not values_b or values_b.get("payload") != "from-A":
        print("FAIL: worker-B did not see worker-A checkpoint", file=sys.stderr)
        return 1

    await _worker_write(label="worker-B", thread_id=thread_id, step=2, payload="from-B")
    values_a = await _worker_read(label="worker-A", thread_id=thread_id)
    if not values_a or values_a.get("payload") != "from-B":
        print("FAIL: worker-A did not see worker-B checkpoint", file=sys.stderr)
        return 1

    await asyncio.gather(
        _worker_write(label="worker-A-concurrent", thread_id=thread_id, step=3, payload="race-A"),
        _worker_write(label="worker-B-concurrent", thread_id=thread_id, step=3, payload="race-B"),
    )
    final = await _worker_read(label="final", thread_id=thread_id)
    if final is None or "payload" not in final:
        print("FAIL: concurrent write left empty state", file=sys.stderr)
        return 1

    print("PASS: cross-worker Postgres checkpointer bake-off")
    return 0


if __name__ == "__main__":
    ensure_psycopg_compatible_loop()
    raise SystemExit(asyncio.run(main()))
