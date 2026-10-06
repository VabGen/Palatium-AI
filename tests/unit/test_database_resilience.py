"""Postgres connection resilience: короткий retry + typed 503 вместо ASGI 500 (035).

Регрессия из эксплуатации: пока Postgres поднимается после рестарта, новые соединения
получают SQLSTATE ``57P03`` («the database system is in recovery mode»), и
``POST /api/attachments/init`` / ``POST /api/intents/process`` отвечали ASGI 500 из
``asyncpg.CannotConnectNowError`` в момент checkout'а соединения.

Здесь зафиксирован контракт: транзиентный сбой повторяется с backoff'ом, а исчерпание
бюджета превращается в типизированный ``DatabaseUnavailableError`` (граница API → 503 +
``Retry-After``). Permanent-ошибки (права, отсутствующая таблица) не маскируются под
недоступность БД — иначе реальный баг прячется за «повторите позже».
"""

from __future__ import annotations

from typing import Any

import asyncpg
import pytest

from sqlalchemy.exc import (
    OperationalError,
    TimeoutError as SATimeoutError,
)

from palatium_ai.core.exceptions import DatabaseUnavailableError
from palatium_ai.core.resilience import RetryPolicy, retry_async
from palatium_ai.infrastructure.database.resilience import (
    DB_BACKOFF_POLICY_INFO_KEY,
    ResilientAsyncSession,
    is_connection_unavailable_error,
    is_transient_connection_error,
)

_CONNECTION_SENTINEL = object()
_NO_ENTER_ATTEMPTS = 0


def _recovery_mode_error() -> asyncpg.CannotConnectNowError:
    """Ровно тот сбой из логов: Postgres ещё не принимает новую работу."""
    return asyncpg.CannotConnectNowError("the database system is in recovery mode")


def _permanent_error() -> asyncpg.UndefinedTableError:
    """Отсутствующая таблица — баг/миграция, а не временная недоступность."""
    return asyncpg.UndefinedTableError('relation "sessions" does not exist')


def _driver_wrapped(exc: BaseException) -> OperationalError:
    """SQLAlchemy заворачивает сбой драйвера в ``DBAPIError.orig`` — как в трейсе."""
    return OperationalError("SELECT 1", {}, exc)


def _pool_timeout_error() -> SATimeoutError:
    """Пул исчерпан: пока Postgres лежит, все соединения заняты попытками connect."""
    return SATimeoutError("QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 30.00")


def _fast_policy(*, max_attempts: int = 3) -> RetryPolicy:
    """Нулевые задержки: сам backoff — предмет тестов ``retry_async``, а не сна в тестах."""
    return RetryPolicy(max_attempts=max_attempts, initial_delay_seconds=0.0, max_delay_seconds=0.0)


class _CheckingOutSession(ResilientAsyncSession):
    """Сессия без engine: checkout соединения заменён сценарием сбоев из ``failures``."""

    def __init__(self, *, policy: RetryPolicy | None, failures: list[BaseException]) -> None:
        if policy is None:
            super().__init__()
        else:
            super().__init__(info={DB_BACKOFF_POLICY_INFO_KEY: policy})
        self.attempts = _NO_ENTER_ATTEMPTS
        self._failures = failures

    async def connection(self) -> Any:  # type: ignore[override]  # подмена порта checkout'а в тесте
        self.attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        return _CONNECTION_SENTINEL


# ── Классификация сбоя ────────────────────────────────────────────────────────────────────────────────────────────


def test_recovery_mode_is_transient_directly_and_through_driver_wrapper() -> None:
    assert is_transient_connection_error(_recovery_mode_error()) is True
    assert is_transient_connection_error(_driver_wrapped(_recovery_mode_error())) is True


def test_saturation_and_socket_failures_are_transient() -> None:
    """53300 (too many connections) и обрыв сокета снимаются повтором так же, как recovery."""
    assert is_transient_connection_error(asyncpg.TooManyConnectionsError("too many clients")) is True
    assert is_transient_connection_error(ConnectionRefusedError(111, "Connection refused")) is True


def test_permanent_and_programming_errors_are_not_transient() -> None:
    assert is_transient_connection_error(_driver_wrapped(_permanent_error())) is False
    assert is_transient_connection_error(ValueError("bad DSN")) is False


def test_pool_starvation_is_unavailable_but_not_retryable() -> None:
    """Исчерпание пула → 503, но повторять его нельзя: каждая попытка стоит весь pool_timeout."""
    assert is_connection_unavailable_error(_pool_timeout_error()) is True
    assert is_transient_connection_error(_pool_timeout_error()) is False


def test_unavailable_predicate_is_wider_than_retryable_one() -> None:
    """``transient ⊂ unavailable``: всё, что ретраится, в 503 тоже маппится."""
    assert is_connection_unavailable_error(_recovery_mode_error()) is True
    assert is_connection_unavailable_error(_driver_wrapped(_permanent_error())) is False
    assert is_connection_unavailable_error(ValueError("bad DSN")) is False


# ── Retry-хелпер ─────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_retry_helper_repeats_transient_failure_then_returns() -> None:
    calls: list[int] = []

    async def _operation() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _recovery_mode_error()
        return "ok"

    result = await retry_async(
        _operation,
        policy=_fast_policy(max_attempts=3),
        is_retryable=is_transient_connection_error,
        description="test operation",
    )

    assert result == "ok"
    assert len(calls) == 3


@pytest.mark.asyncio()
async def test_retry_helper_does_not_retry_permanent_failure() -> None:
    calls: list[int] = []

    async def _operation() -> None:
        calls.append(1)
        raise _permanent_error()

    with pytest.raises(asyncpg.UndefinedTableError):
        await retry_async(
            _operation,
            policy=_fast_policy(max_attempts=3),
            is_retryable=is_transient_connection_error,
            description="test operation",
        )

    assert len(calls) == 1


@pytest.mark.asyncio()
async def test_retry_helper_reraises_last_failure_when_budget_exhausted() -> None:
    calls: list[int] = []

    async def _operation() -> None:
        calls.append(1)
        raise _recovery_mode_error()

    with pytest.raises(asyncpg.CannotConnectNowError):
        await retry_async(
            _operation,
            policy=_fast_policy(max_attempts=3),
            is_retryable=is_transient_connection_error,
            description="test operation",
        )

    assert len(calls) == 3


# ── Резилиентная сессия ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_session_retries_checkout_then_enters() -> None:
    session = _CheckingOutSession(
        policy=_fast_policy(),
        failures=[_recovery_mode_error(), _recovery_mode_error()],
    )

    async with session:
        pass

    assert session.attempts == 3


@pytest.mark.asyncio()
async def test_session_maps_exhausted_budget_to_typed_unavailable() -> None:
    policy = _fast_policy(max_attempts=3)
    session = _CheckingOutSession(policy=policy, failures=[_recovery_mode_error() for _ in range(5)])
    entered = False

    with pytest.raises(DatabaseUnavailableError) as raised:
        async with session:
            entered = True

    assert entered is False
    assert raised.value.operation == "acquire_connection"
    assert raised.value.retry_after_seconds == policy.retry_after_seconds
    assert session.attempts == policy.max_attempts


@pytest.mark.asyncio()
async def test_session_does_not_mask_permanent_failure_as_unavailable() -> None:
    session = _CheckingOutSession(policy=_fast_policy(), failures=[_driver_wrapped(_permanent_error())])

    with pytest.raises(OperationalError):
        async with session:
            pass

    assert session.attempts == 1


@pytest.mark.asyncio()
async def test_pool_starvation_becomes_unavailable_without_retry() -> None:
    """Пул не освободится быстрее от повторов: одна попытка, но ответ всё равно 503."""
    session = _CheckingOutSession(policy=_fast_policy(max_attempts=3), failures=[_pool_timeout_error()])

    with pytest.raises(DatabaseUnavailableError) as raised:
        async with session:
            pass

    assert raised.value.operation == "acquire_connection"
    assert session.attempts == 1


@pytest.mark.asyncio()
async def test_fail_fast_policy_still_types_transient_failure() -> None:
    """``DB_RETRY_ATTEMPTS=1`` — повторов нет, но ответ остаётся 503, а не 500 (035)."""
    session = _CheckingOutSession(policy=_fast_policy(max_attempts=1), failures=[_recovery_mode_error()])
    entered = False

    with pytest.raises(DatabaseUnavailableError):
        async with session:
            entered = True

    assert entered is False
    assert session.attempts == 1


@pytest.mark.asyncio()
async def test_session_without_policy_still_types_transient_failure() -> None:
    """Сессия, собранная мимо ``create_session_factory``, не должна отдавать 57P03 наружу."""
    session = _CheckingOutSession(policy=None, failures=[_recovery_mode_error()])

    with pytest.raises(DatabaseUnavailableError) as raised:
        async with session:
            pass

    assert raised.value.retry_after_seconds >= 1
    assert session.attempts == 1


@pytest.mark.asyncio()
async def test_session_records_retry_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каждый повтор — наблюдаемое событие resilience (040)."""
    recorded: list[tuple[str, str]] = []

    class _MetricsSpy:
        def record_error(self, component: str, kind: str) -> None:
            recorded.append((component, kind))

    monkeypatch.setattr("palatium_ai.infrastructure.database.resilience.agent_metrics", _MetricsSpy())
    session = _CheckingOutSession(policy=_fast_policy(max_attempts=3), failures=[_recovery_mode_error()])

    async with session:
        pass

    assert recorded == [("database", "connection_retry")]


# ── Проводка фабрики (регрессия: обычный async_sessionmaker оставлял 57P03 → 500) ────────────────────────────────


@pytest.mark.asyncio()
async def test_session_factory_wires_resilient_class_and_policy() -> None:
    from palatium_ai.core.config import get_settings
    from palatium_ai.infrastructure.database.runtime import create_session_factory

    settings = get_settings()
    engine, factory = create_session_factory(settings)
    try:
        assert factory.class_ is ResilientAsyncSession
        policy = factory.kw["info"][DB_BACKOFF_POLICY_INFO_KEY]
        assert isinstance(policy, RetryPolicy)
        assert policy.max_attempts == settings.db.retry_attempts
        assert policy.max_delay_seconds == settings.db.retry_max_delay_seconds
    finally:
        await engine.dispose()
