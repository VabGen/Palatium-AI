"""PostgresAttachmentRepository: RLS binding, user predicates, aggregate mapping (060)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from palatium_ai.domain.attachments import Attachment
from palatium_ai.infrastructure.database import attachment_repository as repo_module
from palatium_ai.infrastructure.database.attachment_repository import PostgresAttachmentRepository
from palatium_ai.infrastructure.database.models import AttachmentORM

pytestmark = pytest.mark.asyncio

_USER = "user-a"
_CREATED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class _Result:
    """Minimal stand-in for a SQLAlchemy ``Result`` covering the shapes we use."""

    def __init__(self, *, one: object = None, many: list[object] | None = None, scalar: int = 0) -> None:
        self._one = one
        self._many = many or []
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._one

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._many

    def scalar_one(self) -> int:
        return self._scalar


def _orm(**overrides: object) -> AttachmentORM:
    values: dict[str, object] = {
        "id": uuid4(),
        "user_id": _USER,
        "thread_id": "thread-1",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "blob_key": "attachments/abc",
        "mode": "attach",
        "status": "ready",
        "page_count": 3,
        "derived_text_key": None,
        "rejection_reason": None,
        "error": None,
        "created_at": _CREATED_AT,
        "expires_at": None,
    }
    values.update(overrides)
    return AttachmentORM(**values)


def _attachment(**overrides: object) -> Attachment:
    values: dict[str, object] = {
        "id": uuid4(),
        "user_id": _USER,
        "thread_id": "thread-1",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "blob_key": "attachments/abc",
        "mode": "attach",
        "status": "pending",
        "created_at": _CREATED_AT,
    }
    values.update(overrides)
    return Attachment(**values)


class _SessionFactory:
    """Fake ``async_sessionmaker`` recording the session it handed out."""

    def __init__(self, result: _Result | None = None) -> None:
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=result if result is not None else _Result())
        # Order matters: the RLS scope is transaction-local, so a reload must stay
        # inside the transaction that bound it.
        self.calls: list[str] = []
        self.session.commit = AsyncMock(side_effect=lambda *_args: self.calls.append("commit"))
        self.session.flush = AsyncMock(side_effect=lambda *_args: self.calls.append("flush"))
        self.session.refresh = AsyncMock(side_effect=lambda *_args: self.calls.append("refresh"))
        self.session.add = MagicMock()
        self.opened = 0

    def __call__(self) -> _SessionFactory:
        self.opened += 1
        return self

    async def __aenter__(self) -> MagicMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.fixture()
def rls_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, str]]:
    """Record scope bindings instead of executing Postgres-only ``set_config``."""
    calls: list[tuple[object, str]] = []

    async def _record(session: object, user_id: str) -> None:
        calls.append((session, user_id))

    monkeypatch.setattr(repo_module, "set_rls_user_scope", _record)
    return calls


async def test_create_binds_rls_scope_and_inserts(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory(_Result(one=None))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]
    attachment = _attachment()

    result = await repository.create(attachment)

    assert rls_calls == [(factory.session, _USER)]
    factory.session.add.assert_called_once()
    assert result.id == attachment.id
    assert result.status == "pending"


async def test_create_reloads_before_commit_keeps_the_rls_scope(rls_calls: list[tuple[object, str]]) -> None:
    """Regression: ``set_config(..., is_local=true)`` dies with the transaction.

    Reloading via ``refresh()`` after ``commit()`` would run in a new transaction
    with no ``palatium.user_id`` bound, so the FORCE RLS predicate would be false
    and the insert path would fail on its own read-back (060).
    """
    factory = _SessionFactory(_Result(one=None))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    await repository.create(_attachment())

    assert factory.calls.index("refresh") < factory.calls.index("commit")


async def test_save_binds_rls_scope_and_returns_updated_aggregate(rls_calls: list[tuple[object, str]]) -> None:
    entity = _orm(status="indexed", mode="index")
    factory = _SessionFactory(_Result(one=entity))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    result = await repository.save(_attachment())

    assert rls_calls == [(factory.session, _USER)]
    assert result.status == "indexed"
    assert result.mode == "index"


async def test_save_raises_when_no_row_matches_the_owner(rls_calls: list[tuple[object, str]]) -> None:
    """A silent no-op update would leave a state transition unpersisted."""
    repository = PostgresAttachmentRepository(_SessionFactory(_Result(one=None)))  # type: ignore[arg-type]
    with pytest.raises(LookupError):
        await repository.save(_attachment())


async def test_get_binds_rls_scope_and_scopes_by_user(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory(_Result(one=_orm()))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    found = await repository.get(uuid4(), user_id=_USER)

    assert found is not None
    assert rls_calls == [(factory.session, _USER)]
    statement = str(factory.session.execute.await_args.args[0])
    assert "user_id" in statement


async def test_get_returns_none_when_absent(rls_calls: list[tuple[object, str]]) -> None:
    repository = PostgresAttachmentRepository(_SessionFactory(_Result(one=None)))  # type: ignore[arg-type]
    assert await repository.get(uuid4(), user_id=_USER) is None


async def test_get_many_short_circuits_on_empty_ids(rls_calls: list[tuple[object, str]]) -> None:
    """Avoids an ``IN ()`` round trip — and must not touch the database at all."""
    factory = _SessionFactory()
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    assert await repository.get_many([], user_id=_USER) == []
    assert factory.opened == 0
    assert rls_calls == []


async def test_get_many_binds_rls_scope_when_ids_are_present(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory(_Result(many=[_orm(), _orm()]))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    found = await repository.get_many([UUID(int=1), UUID(int=2)], user_id=_USER)

    assert len(found) == 2
    assert rls_calls == [(factory.session, _USER)]
    assert "user_id" in str(factory.session.execute.await_args.args[0])


async def test_list_for_thread_binds_rls_scope_and_scopes_by_user(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory(_Result(many=[_orm()]))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    found = await repository.list_for_thread("thread-1", user_id=_USER)

    assert len(found) == 1
    assert rls_calls == [(factory.session, _USER)]
    statement = str(factory.session.execute.await_args.args[0])
    assert "thread_id" in statement
    assert "user_id" in statement


async def test_count_for_thread_binds_rls_scope(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory(_Result(scalar=3))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    assert await repository.count_for_thread("thread-1", user_id=_USER) == 3
    assert rls_calls == [(factory.session, _USER)]
    assert "user_id" in str(factory.session.execute.await_args.args[0])


async def test_delete_binds_rls_scope_and_scopes_by_user(rls_calls: list[tuple[object, str]]) -> None:
    factory = _SessionFactory()
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    await repository.delete(uuid4(), user_id=_USER)

    assert rls_calls == [(factory.session, _USER)]
    assert "user_id" in str(factory.session.execute.await_args.args[0])
    factory.session.commit.assert_awaited_once()


async def test_every_operation_binds_the_rls_scope(rls_calls: list[tuple[object, str]]) -> None:
    """Regression guard for the invariant this adapter's isolation depends on."""
    factory = _SessionFactory(_Result(one=_orm(), many=[_orm()]))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    await repository.create(_attachment())
    await repository.save(_attachment())
    await repository.get(uuid4(), user_id=_USER)
    await repository.get_many([UUID(int=3)], user_id=_USER)
    await repository.list_for_thread("thread-1", user_id=_USER)
    await repository.count_for_thread("thread-1", user_id=_USER)
    await repository.delete(uuid4(), user_id=_USER)
    await repository.list_expired(_CREATED_AT, user_id=_USER, limit=10)

    assert [uid for _session, uid in rls_calls] == [_USER] * 8


async def test_list_expired_is_user_scoped_and_ttl_bounded(rls_calls: list[tuple[object, str]]) -> None:
    """Retention cannot be cross-tenant with the app role, so the predicate is explicit."""
    factory = _SessionFactory(_Result(many=[_orm(expires_at=_CREATED_AT)]))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    found = await repository.list_expired(_CREATED_AT, user_id=_USER, limit=25)

    assert len(found) == 1
    assert rls_calls == [(factory.session, _USER)]
    statement = str(factory.session.execute.await_args.args[0])
    assert "user_id" in statement
    assert "expires_at" in statement
    assert "LIMIT" in statement.upper()


async def test_refusal_state_round_trips_through_the_mapper(rls_calls: list[tuple[object, str]]) -> None:
    entity = _orm(status="quarantined", rejection_reason="malware_detected", error="Eicar", page_count=None)
    repository = PostgresAttachmentRepository(_SessionFactory(_Result(one=entity)))  # type: ignore[arg-type]

    found = await repository.get(uuid4(), user_id=_USER)

    assert found is not None
    assert found.status == "quarantined"
    assert found.rejection_reason == "malware_detected"
    assert not found.is_usable
