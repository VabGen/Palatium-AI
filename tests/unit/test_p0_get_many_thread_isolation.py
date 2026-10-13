"""P0-A: get_many must isolate by thread_id (cross-thread UUID leakage).

Root (A.1 / A.4): ``build_turn_context(thread_id=…)`` must reach
``get_many(ids, user_id=…, thread_id=…)``. Without the thread predicate,
rehydrate resolves a UUID from another thread of the same user into fence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from palatium_ai.infrastructure.database import attachment_repository as repo_module
from palatium_ai.infrastructure.database.attachment_repository import PostgresAttachmentRepository
from palatium_ai.infrastructure.database.models import AttachmentORM

pytestmark = pytest.mark.asyncio

_USER = "user-p0"
_THREAD_T1 = "thread-T1"
_THREAD_T2 = "thread-T2"
_CREATED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_A1_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_A2_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class _Result:
    def __init__(self, *, many: list[object] | None = None) -> None:
        self._many = many or []

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._many


def _orm(*, attachment_id: UUID, thread_id: str, filename: str) -> AttachmentORM:
    return AttachmentORM(
        id=attachment_id,
        user_id=_USER,
        thread_id=thread_id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=1024,
        blob_key=f"attachments/{attachment_id}",
        mode="attach",
        status="ready",
        page_count=1,
        derived_text_key=None,
        rejection_reason=None,
        error=None,
        project_id=None,
        contains_pii=False,
        created_at=_CREATED_AT,
        expires_at=None,
    )


class _SessionFactory:
    def __init__(self, result: _Result) -> None:
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=result)
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
    calls: list[tuple[object, str]] = []

    async def _record(session: object, user_id: str) -> None:
        calls.append((session, user_id))

    monkeypatch.setattr(repo_module, "set_rls_user_scope", _record)
    return calls


async def test_get_many_filters_by_thread_id_not_only_user(
    rls_calls: list[tuple[object, str]],
) -> None:
    """Desired contract: get_many(..., thread_id=T2) must put thread_id in SQL.

    Seed conceptually: A1∈T1, A2∈T2, same user. Caller asks for both UUIDs while
    operating in T2 — only A2 may be eligible. Current signature has no
    ``thread_id``; current SQL has no ``thread_id`` predicate → P0 leakage.
    """
    a1 = _orm(attachment_id=_A1_ID, thread_id=_THREAD_T1, filename="contract.txt")
    a2 = _orm(attachment_id=_A2_ID, thread_id=_THREAD_T2, filename="otziv_SED_NCPI_RB.pdf")
    # Mock returns both rows — stands in for "DB would return both without thread filter".
    factory = _SessionFactory(_Result(many=[a1, a2]))
    repository = PostgresAttachmentRepository(factory)  # type: ignore[arg-type]

    found = await repository.get_many(
        [_A1_ID, _A2_ID],
        user_id=_USER,
        thread_id=_THREAD_T2,
    )

    assert rls_calls == [(factory.session, _USER)]
    statement = str(factory.session.execute.await_args.args[0])
    assert "user_id" in statement
    assert "thread_id" in statement, (
        "P0: get_many SQL must filter thread_id; without it UUIDs from other "
        "threads of the same user resolve into the current untrusted_context"
    )
    # Once the SQL filter exists, the adapter must not surface foreign-thread rows
    # even if the session mock is over-broad (contract for the post-fix world).
    assert {row.id for row in found} == {_A2_ID}
