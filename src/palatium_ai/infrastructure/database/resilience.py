# src/palatium_ai/infrastructure/database/resilience.py

"""Устойчивость async-сессии к короткому отказу Postgres (020, 035).

Рестарт Postgres (ручной restart, обновление, crash recovery) отвечает на новые
соединения SQLSTATE ``57P03`` — «the database system is in recovery mode» — и
рвёт соединения из пула. Это *expected operational error* (035), а не баг: его
следует коротко повторить, а если отказ живёт дольше бюджета — поднять типизированный
:class:`~palatium_ai.core.exceptions.DatabaseUnavailableError`, чтобы API ответил
``503`` + ``Retry-After`` вместо ASGI 500 (035: маппинг на границе).

Область намеренно узкая: ретраится только **получение соединения**, поэтому ни один
statement не выполняется дважды (повтор запроса — ответственность вызывающего кода,
а не транспортного слоя). Исчерпание пула (``pool_timeout``) не ретраится, но тоже
маппится в 503: это тот же класс «БД недоступна», а не ошибка запроса.
"""

from __future__ import annotations

import contextlib

from collections.abc import Iterator
from typing import TYPE_CHECKING

import asyncpg
import structlog

from sqlalchemy.exc import (
    DisconnectionError,
    TimeoutError as SATimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from palatium_ai.core.exceptions import DatabaseUnavailableError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.resilience import RetryPolicy, retry_async

if TYPE_CHECKING:
    from tenacity import RetryCallState

logger = structlog.get_logger(__name__)

DB_BACKOFF_POLICY_INFO_KEY = "db_backoff_policy"
"""Ключ :class:`RetryPolicy` в ``session.info`` (задаётся ``async_sessionmaker(info=...)``)."""

# SQLSTATE, которые Postgres отдаёт, когда он ещё не принимает новую работу:
# 53300 too_many_connections · 57P01 admin_shutdown · 57P02 crash_shutdown ·
# 57P03 cannot_connect_now («recovery mode») · 08xxx connection_exception.
_TRANSIENT_SQLSTATES = frozenset(
    {"53300", "57P01", "57P02", "57P03", "08000", "08001", "08003", "08004", "08006", "08P01"},
)


def is_transient_connection_error(exc: BaseException) -> bool:
    """True для сбоя, который снимается коротким повтором (recovery mode, обрыв сокета).

    Цепочка исключений обходится целиком: SQLAlchemy заворачивает ошибку драйвера в
    ``DBAPIError.orig``, asyncpg добавляет ``__cause__``/``__context__``, а под
    ними лежит исходная ``asyncpg``-ошибка с ``sqlstate``.
    """
    for candidate in _exception_chain(exc):
        sqlstate = getattr(candidate, "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate in _TRANSIENT_SQLSTATES:
            return True
        if isinstance(candidate, (asyncpg.PostgresConnectionError, DisconnectionError)):
            return True
        # Socket layer: ECONNREFUSED/ECONNRESET/ETIMEDOUT, DNS, connect timeout.
        if isinstance(candidate, OSError):
            return True
    return False


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc`` и его cause/context/orig, без зацикливания на самоссылках."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(
            linked
            for linked in (current.__cause__, current.__context__, getattr(current, "orig", None))
            if isinstance(linked, BaseException) and id(linked) not in seen
        )


def is_connection_unavailable_error(exc: BaseException) -> bool:
    """True для сбоя, о котором клиенту честно ответить ``503`` (035).

    Шире, чем :func:`is_transient_connection_error`: сюда попадает и «соединение
    не добыть из пула» — пока Postgres лежит, все соединения заняты попытками
    подключиться, и запрос умирает по ``pool_timeout``. Повторять такой сбой
    бессмысленно (каждая попытка стоит весь таймаут), но и до ASGI 500 он доходить
    не должен: запрос не выполнялся, значит retry клиента безопасен.
    """
    if is_transient_connection_error(exc):
        return True
    return any(isinstance(candidate, SATimeoutError) for candidate in _exception_chain(exc))


class ResilientAsyncSession(AsyncSession):
    """``AsyncSession``, у которой *получение соединения* переживает короткий отказ БД.

    Вход в ``async with`` сначала резервирует соединение из пула (с pre-ping) под
    retry-политикой из ``session.info`` — поэтому ``CannotConnectNowError`` не
    долетает до endpoint'а как ASGI 500, а превращается в 503 (после ретраев).
    """

    async def __aenter__(self) -> ResilientAsyncSession:
        """Зарезервировать соединение (с retry), затем отдать сессию вызывающему."""
        try:
            await self._ensure_connected()
        except Exception:
            # Не оставлять утёкшую сессию: сбой на подключении уже привязал транзакцию.
            await self._close_quietly()
            raise
        return self

    async def _ensure_connected(self) -> None:
        """Получить соединение один раз, с backoff'ом на транзиентных сбоях."""
        if self.in_transaction():
            return  # соединение уже привязано вызывающим кодом (например, через session.begin())
        policy = self._backoff_policy()
        try:
            if policy is None or not policy.is_enabled:
                # Fail-fast (`max_attempts == 1`) — осознанный отказ от повторов, но не
                # от типизации: 503 остаётся 503, а не ASGI 500 (035).
                await self.connection()
                return
            await retry_async(
                self.connection,
                policy=policy,
                is_retryable=is_transient_connection_error,
                description="database connection acquisition",
                on_retry=_record_connect_retry,
            )
        except Exception as exc:
            if not is_connection_unavailable_error(exc):
                # Ошибка конфигурации/прав: падать громко, не маскировать под недоступность.
                raise
            await self._release_failed_transaction()
            raise DatabaseUnavailableError(
                operation="acquire_connection",
                retry_after_seconds=_retry_after_seconds(policy),
            ) from exc

    def _backoff_policy(self) -> RetryPolicy | None:
        policy = self.info.get(DB_BACKOFF_POLICY_INFO_KEY)
        return policy if isinstance(policy, RetryPolicy) else None

    async def _release_failed_transaction(self) -> None:
        """Сбросить отравленную транзакцию, которую драйвер мог открыть до сбоя ping'а."""
        if not self.in_transaction():
            return
        with contextlib.suppress(Exception):
            await super().rollback()

    async def _close_quietly(self) -> None:
        """Закрыть сессию, не подменяя исходную ошибку (её собственный сбой вторичен)."""
        with contextlib.suppress(Exception):
            await super().close()


_FAIL_FAST_RETRY_AFTER_SECONDS = 1
"""``Retry-After``, когда политика не передана: повторов нет, но 503 остаётся типизированным (035)."""


def _retry_after_seconds(policy: RetryPolicy | None) -> int:
    """Подсказка клиенту берётся из политики; без неё — минимальный осмысленный срок."""
    return policy.retry_after_seconds if policy is not None else _FAIL_FAST_RETRY_AFTER_SECONDS


def _record_connect_retry(_state: RetryCallState) -> None:
    """Повтор подключения — наблюдаемое событие resilience (040)."""
    agent_metrics.record_error("database", "connection_retry")
