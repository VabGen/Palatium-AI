# src/palatium_ai/core/resilience/retry.py

"""Retry с экспоненциальным backoff (020, 035).

Единственное место, где живёт retry-цикл с backoff (035: «retry/backoff/circuit
breaker — только core/resilience»). Вызывающий отдаёт операцию, политику из
конфига и предикат классификации сбоя; helper владеет числом попыток, задержкой
с jitter'ом, логом и метрикой. Задержки — из конфига, не магические числа (050).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

if TYPE_CHECKING:
    from tenacity import RetryCallState

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Границы retry для одной операции (значения — из конфига)."""

    max_attempts: int
    initial_delay_seconds: float
    max_delay_seconds: float

    @property
    def is_enabled(self) -> bool:
        """``max_attempts == 1`` — осознанный fail-fast без повторов."""
        return self.max_attempts > 1

    @property
    def retry_after_seconds(self) -> int:
        """Подсказка клиенту (``Retry-After``) на случай исчерпания бюджета.

        Верхняя граница одной паузы, округлённая вверх до секунды: раньше этого
        срока повтор бессмысленен, и клиенту не сообщается «retry now».
        """
        return max(1, int(self.max_delay_seconds) + (1 if self.max_delay_seconds % 1 else 0))


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    is_retryable: Callable[[BaseException], bool],
    description: str,
    on_retry: Callable[[RetryCallState], None] | None = None,
) -> T:
    """Выполнить ``operation`` с backoff'ом, пробросив последний сбой наружу.

    ``is_retryable`` решает судьбу каждого сбоя: неретраибельная ошибка
    поднимается сразу, без паузы. При исчерпании попыток исключение
    пробрасывается как есть (``reraise=True``) — вызывающий сохраняет исходную
    причину для собственного маппинга (035).
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max(1, policy.max_attempts)),
        wait=wait_exponential_jitter(
            initial=max(0.0, policy.initial_delay_seconds),
            max=max(policy.initial_delay_seconds, policy.max_delay_seconds),
        ),
        retry=retry_if_exception(is_retryable),
        reraise=True,
        before_sleep=_before_sleep(description, on_retry),
    ):
        with attempt:
            return await operation()
    raise RuntimeError(f"{description}: retry loop exited without a result")  # pragma: no cover


def _before_sleep(
    description: str,
    on_retry: Callable[[RetryCallState], None] | None,
) -> Callable[[RetryCallState], None]:
    """Логировать каждый запланированный повтор (040) и отдать состояние в метрику."""

    def _hook(state: RetryCallState) -> None:
        outcome = state.outcome
        error = outcome.exception() if outcome is not None else None
        sleep_seconds = state.next_action.sleep if state.next_action is not None else None
        logger.warning(
            "retry.scheduled",
            action=description,
            attempt=state.attempt_number,
            error_type=type(error).__name__ if error is not None else None,
            sleep_seconds=round(sleep_seconds, 3) if sleep_seconds is not None else None,
        )
        if on_retry is not None:
            on_retry(state)

    return _hook
