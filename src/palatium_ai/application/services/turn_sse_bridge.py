# src/palatium_ai/application/services/turn_sse_bridge.py

"""Per-turn asyncio queue for mid-graph SSE deltas (formatter token stream, W1.4)."""

from __future__ import annotations

import asyncio
import time

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TurnSseBridge:
    """Queue of SSE event dicts emitted from inside graph nodes."""

    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    # Monotonic start for SSE TTFT (first user-visible answer_delta).
    started_at: float = field(default_factory=time.perf_counter)
    has_emitted_answer: bool = False
    sse_ttft_recorded: bool = False

    async def emit(self, event: dict[str, Any]) -> None:
        """Enqueue one SSE event (non-blocking for the consumer loop)."""
        await self.queue.put(event)

    def emit_nowait(self, event: dict[str, Any]) -> None:
        """Enqueue without awaiting (formatter hot path)."""
        self.queue.put_nowait(event)


_current: ContextVar[TurnSseBridge | None] = ContextVar("turn_sse_bridge", default=None)


def get_turn_sse_bridge() -> TurnSseBridge | None:
    """Return SSE bridge for the active streaming turn, if any."""
    return _current.get()


@contextmanager
def turn_sse_bridge(bridge: TurnSseBridge) -> Iterator[TurnSseBridge]:
    """Bind SSE bridge for one ``process_stream`` turn."""
    token: Token[TurnSseBridge | None] = _current.set(bridge)
    try:
        yield bridge
    finally:
        _current.reset(token)
