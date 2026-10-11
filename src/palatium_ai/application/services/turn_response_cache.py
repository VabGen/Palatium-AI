# src/palatium_ai/application/services/turn_response_cache.py

"""Per-turn ContextVar for L1 Formatter response-cache probe (P0.2 / W1.2).

Bound by IntentService around graph invoke; probed in formatter_node with
strategy + source fingerprint so prior-dependent format turns cannot collide.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.policies.response_cache import ResponseCacheKeyPolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.response_cache_service import ResponseCacheService
    from palatium_ai.domain.agents.formatter import FormatterInput, FormatterTaskResult
    from palatium_ai.domain.policies.types import ExecutionStrategy

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnResponseCacheContext:
    """Tenant + user text for L1 lookup during the active turn."""

    cache: ResponseCacheService
    tenant_key: str
    user_text: str


_current: ContextVar[TurnResponseCacheContext | None] = ContextVar(
    "turn_response_cache",
    default=None,
)


def get_turn_response_cache() -> TurnResponseCacheContext | None:
    """Return L1 cache bind for the active turn, if any."""
    return _current.get()


@contextmanager
def turn_response_cache(ctx: TurnResponseCacheContext) -> Iterator[TurnResponseCacheContext]:
    """Bind L1 response-cache params for one IntentService turn."""
    token: Token[TurnResponseCacheContext | None] = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


async def try_cached_formatter_result(
    *,
    task_input: FormatterInput,
    selected_strategy: ExecutionStrategy | str | None,
) -> FormatterTaskResult | None:
    """Probe L1 for an exact-repeat (tenant + text + locale + strategy + source)."""
    ctx = get_turn_response_cache()
    if ctx is None or not ctx.cache.enabled:
        return None
    if not selected_strategy or not ResponseCacheKeyPolicy.is_cacheable_strategy(str(selected_strategy)):
        return None
    hit = await ctx.cache.get(
        tenant_key=ctx.tenant_key,
        user_text=ctx.user_text,
        locale=task_input.response_locale,
        strategy=selected_strategy,
        source_content=task_input.worker_summary or "",
    )
    if hit is None:
        agent_metrics.record_cache_miss(cache_layer="l1_response")
        return None
    agent_metrics.record_cache_hit(cache_layer="l1_response")
    logger.info(
        "formatter.cache_hit",
        strategy=str(selected_strategy),
        task_id=task_input.task_id,
    )
    return hit.model_copy(update={"task_id": task_input.task_id})
