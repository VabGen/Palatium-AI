"""Cost attribution tracker with Redis storage."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from palatium_ai.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

_TTL_SECONDS = 400 * 24 * 3600  # 400 дней


class CostTracker:
    """Per-org / per-user daily cost aggregation in Redis (Phase 3)."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def record(
        self,
        *,
        org_id: str,
        user_id: str,
        agent_role: str,
        model: str,
        cost_usd: float,
    ) -> None:
        """Record cost for org and user with daily aggregation."""
        if cost_usd <= 0.0:
            return
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        safe_org = (org_id or "default").strip() or "default"
        safe_user = (user_id or "anonymous").strip() or "anonymous"
        safe_role = (agent_role or "unknown").strip() or "unknown"

        org_key = f"cost:{safe_org}:{day}"
        # redis-py stubs: basedpyright sees ``T | Awaitable[T]``; mypy already narrows
        # to Awaitable — cast is for pyright only (017 TOOL_LIMITATION).
        await cast(  # type: ignore[redundant-cast]
            "Awaitable[float]", self._redis.hincrbyfloat(org_key, safe_role, cost_usd)
        )
        await cast(  # type: ignore[redundant-cast]
            "Awaitable[bool]", self._redis.expire(org_key, _TTL_SECONDS)
        )

        user_key = f"cost:user:{safe_user}:{day}"
        await cast(  # type: ignore[redundant-cast]
            "Awaitable[float]", self._redis.hincrbyfloat(user_key, "total", cost_usd)
        )
        await cast(  # type: ignore[redundant-cast]
            "Awaitable[bool]", self._redis.expire(user_key, _TTL_SECONDS)
        )

        logger.debug(
            "cost_tracker.record",
            org_id=safe_org,
            user_id=safe_user,
            agent_role=safe_role,
            model=model,
            cost_usd=cost_usd,
        )
