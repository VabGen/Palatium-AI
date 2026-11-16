# src/palatium_ai/application/services/turn_attachment_context.py

"""Per-turn ContextVar for mid-graph attachment rehydrate (Super Brain SB2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from palatium_ai.domain.attachments.context import AttachmentTurnContext

RehydrateFn = Callable[[Sequence[UUID]], Awaitable[str]]
ClearPendingFn = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TurnAttachmentContext:
    """Callbacks to fence attachments / clear sticky pending mid-graph.

    ``primed`` is the context the turn entry already built. Rehydrating exactly those
    ids must reuse it: a second read of the same rows and blobs inside one turn buys
    nothing and showed up in the logs as a duplicated ``build_turn_context`` call (P5).
    """

    rehydrate: RehydrateFn | None = None
    clear_pending: ClearPendingFn | None = None
    primed: AttachmentTurnContext | None = None


_current: ContextVar[TurnAttachmentContext | None] = ContextVar(
    "turn_attachment_context",
    default=None,
)


def get_turn_attachment_context() -> TurnAttachmentContext | None:
    """Return attachment callbacks for the active turn, if any."""
    return _current.get()


@contextmanager
def turn_attachment_context(ctx: TurnAttachmentContext) -> Iterator[TurnAttachmentContext]:
    """Bind attachment callbacks for one IntentService turn."""
    token: Token[TurnAttachmentContext | None] = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
