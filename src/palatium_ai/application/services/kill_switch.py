# src/palatium_ai/application/services/kill_switch.py

"""Global emergency stop (kill switch) for agent turns."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

from palatium_ai.core.exceptions import PalatiumError
from palatium_ai.core.observability.audit import get_audit_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

_REDIS_KEY = "palatium:kill_switch:engaged"


class KillSwitchEngagedError(PalatiumError):
    """Raised when a turn is blocked by the platform kill switch."""


class KillSwitchService:
    """Process-local + optional Redis-backed global kill switch."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client
        self._local_engaged = False
        self._lock = Lock()

    async def is_engaged(self) -> bool:
        """Return True when new agent turns must be rejected."""
        if self._redis is not None:
            raw = await self._redis.get(_REDIS_KEY)
            if raw is None:
                return False
            if isinstance(raw, bytes):
                return raw.decode("utf-8") == "1"
            return str(raw) == "1"
        with self._lock:
            return self._local_engaged

    async def engage(self, *, actor: str, reason: str) -> None:
        """Engage kill switch and write audit event."""
        if self._redis is not None:
            await self._redis.set(_REDIS_KEY, "1")
        else:
            with self._lock:
                self._local_engaged = True
        await _audit(
            event="kill_switch_engaged",
            metadata={"actor": actor, "reason": reason[:500]},
        )

    async def release(self, *, actor: str) -> None:
        """Release kill switch and write audit event."""
        if self._redis is not None:
            await self._redis.delete(_REDIS_KEY)
        else:
            with self._lock:
                self._local_engaged = False
        await _audit(
            event="kill_switch_released",
            metadata={"actor": actor},
        )

    async def assert_clear(self, *, conversation_id: str) -> None:
        """Fail closed when engaged; audit blocked turn attempts."""
        if not await self.is_engaged():
            return
        await _audit(
            event="kill_switch_blocked_turn",
            metadata={"conversation_id": conversation_id},
            conversation_id=conversation_id,
        )
        raise KillSwitchEngagedError("Platform kill switch is engaged")


async def _audit(
    *,
    event: str,
    metadata: dict[str, str],
    conversation_id: str = "platform",
) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )
