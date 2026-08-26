# src/palatium_ai/application/services/cost_budget.py

"""Hard cost budgets (turn + daily tenant) — fail closed when exceeded."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

from palatium_ai.core.exceptions import PalatiumError
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector

if TYPE_CHECKING:
    from redis.asyncio import Redis


class CostBudgetExceededError(PalatiumError):
    """Raised when a turn or daily cost budget would be exceeded."""


class CostBudgetService:
    """Enforce optional USD budgets for LLM spend."""

    def __init__(
        self,
        *,
        turn_budget_usd: float = 0.0,
        daily_budget_usd: float = 0.0,
        redis_client: Redis | None = None,
    ) -> None:
        self._turn_budget = max(0.0, turn_budget_usd)
        self._daily_budget = max(0.0, daily_budget_usd)
        self._redis = redis_client
        self._local_daily: dict[str, float] = {}
        self._lock = Lock()

    @property
    def turn_budget_usd(self) -> float:
        """Per-turn USD cap (0 disables)."""
        return self._turn_budget

    @property
    def daily_budget_usd(self) -> float:
        """Per-tenant daily USD cap (0 disables)."""
        return self._daily_budget

    def assert_turn_allows_call(self, *, estimated_next_usd: float = 0.0) -> None:
        """Fail closed when the active turn has already hit its USD budget."""
        if self._turn_budget <= 0:
            return
        collector = get_turn_token_collector()
        spent = 0.0
        if collector is not None:
            spent = sum(item.cost_usd for item in collector.usages)
        projected = spent + max(0.0, estimated_next_usd)
        if projected > self._turn_budget:
            raise CostBudgetExceededError(
                f"Turn cost budget exceeded: spent={spent:.6f} projected={projected:.6f} budget={self._turn_budget:.6f}"
            )

    async def assert_daily_allows_turn(self, *, tenant_key: str) -> None:
        """Fail closed when the tenant daily USD budget is already exhausted."""
        if self._daily_budget <= 0:
            return
        spent = await self._read_daily(tenant_key)
        if spent >= self._daily_budget:
            await _audit(
                event="cost_budget_daily_blocked",
                conversation_id=tenant_key,
                metadata={
                    "spent_usd": f"{spent:.6f}",
                    "budget_usd": f"{self._daily_budget:.6f}",
                },
            )
            raise CostBudgetExceededError(
                f"Daily cost budget exceeded for '{tenant_key}': spent={spent:.6f} budget={self._daily_budget:.6f}"
            )

    async def record_turn_cost(self, *, tenant_key: str, cost_usd: float) -> None:
        """Accumulate daily spend after a completed turn."""
        if self._daily_budget <= 0 or cost_usd <= 0:
            return
        await self._add_daily(tenant_key, cost_usd)

    async def _read_daily(self, tenant_key: str) -> float:
        key = _daily_redis_key(tenant_key)
        if self._redis is not None:
            raw = await self._redis.get(key)
            if raw is None:
                return 0.0
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            try:
                return float(text)
            except ValueError:
                return 0.0
        with self._lock:
            return self._local_daily.get(key, 0.0)

    async def _add_daily(self, tenant_key: str, cost_usd: float) -> None:
        key = _daily_redis_key(tenant_key)
        if self._redis is not None:
            await self._redis.incrbyfloat(key, cost_usd)
            await self._redis.expire(key, 48 * 60 * 60)
            return
        with self._lock:
            self._local_daily[key] = self._local_daily.get(key, 0.0) + cost_usd


def _daily_redis_key(tenant_key: str) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    safe = tenant_key.strip() or "anonymous"
    return f"palatium:cost:daily:{safe}:{day}"


async def _audit(*, event: str, conversation_id: str, metadata: dict[str, str]) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )
