# src/palatium_ai/application/services/turn_recall_context.py

"""Per-turn ContextVar for deferred durable memory recall (P1.5).

IntentGraphRunner binds params before ``ainvoke``; continuation_node loads
durable recall only when MemoryRecallPolicy allows it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.memory.scratchpad import SessionScratchpad


@dataclass(frozen=True, slots=True)
class TurnRecallContext:
    """Parameters needed to run ``recall_for_thread`` mid-graph."""

    memory_port: MemoryPort | None
    thread_id: str
    query: str
    user_id: str | None
    org_id: str | None
    limit: int
    max_chars: int
    min_confidence: float
    scratchpad: SessionScratchpad | None


_current: ContextVar[TurnRecallContext | None] = ContextVar("turn_recall_context", default=None)


def get_turn_recall_context() -> TurnRecallContext | None:
    """Return recall params for the active turn, if any."""
    return _current.get()


@contextmanager
def turn_recall_context(ctx: TurnRecallContext) -> Iterator[TurnRecallContext]:
    """Bind recall params for one IntentService turn."""
    token: Token[TurnRecallContext | None] = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
