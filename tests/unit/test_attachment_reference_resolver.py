"""AttachmentReferenceResolver — owner/thread scoped resolution before a re-read (020, 070)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.attachment_reference_resolver import (
    AttachmentReferenceResolver,
)
from palatium_ai.domain.attachments.models import Attachment


def _attachment(
    filename: str,
    *,
    user_id: str = "user-1",
    thread_id: str = "thread-1",
    status: str = "ready",
) -> Attachment:
    return Attachment(
        id=uuid4(),
        user_id=user_id,
        thread_id=thread_id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=1024,
        blob_key=f"attachments/{uuid4().hex}",
        mode="attach",
        status=status,  # type: ignore[arg-type]  # Literal registry (017)
        created_at=datetime.now(UTC),
    )


class _FakeRepository:
    """Stand-in for ``AttachmentRepositoryPort``; records the scoping it was asked for."""

    def __init__(self, rows: list[Attachment]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, str]] = []

    async def list_for_thread(self, thread_id: str, *, user_id: str) -> list[Attachment]:
        self.calls.append((thread_id, user_id))
        return [row for row in self._rows if row.thread_id == thread_id and row.user_id == user_id]


@pytest.mark.asyncio()
async def test_single_ready_file_resolves_for_its_owner_thread() -> None:
    row = _attachment("СФУТ 9.03-2025.pdf")
    repository = _FakeRepository([row])
    resolver = AttachmentReferenceResolver(repository=repository)

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай этот файл")

    assert resolution.status == "resolved"
    assert resolution.attachment_id == row.id
    assert repository.calls == [("thread-1", "user-1")]


@pytest.mark.asyncio()
async def test_another_users_row_is_not_visible() -> None:
    foreign = _attachment("чужой.pdf", user_id="user-2")
    resolver = AttachmentReferenceResolver(repository=_FakeRepository([foreign]))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай файл")

    assert resolution.status == "no_candidates"
    assert resolution.attachment_id is None


@pytest.mark.asyncio()
async def test_another_threads_row_is_not_visible() -> None:
    other_thread = _attachment("старый.pdf", thread_id="thread-2")
    resolver = AttachmentReferenceResolver(repository=_FakeRepository([other_thread]))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай файл")

    assert resolution.status == "no_candidates"


@pytest.mark.asyncio()
async def test_rows_that_are_not_readable_are_reported_honestly() -> None:
    """A retention-reclaimed row is not «вы не приложили файл» — it is unavailable."""
    expired = _attachment("СФУТ 9.03-2025.pdf", status="expired")
    resolver = AttachmentReferenceResolver(repository=_FakeRepository([expired]))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай файл")

    assert resolution.status == "no_candidates"
    assert resolution.reason == "thread_files_not_readable"
    from palatium_ai.domain.policies.file_reference import FileReferencePolicy

    message = FileReferencePolicy.refusal_message(resolution)
    assert "недоступен" in message


@pytest.mark.asyncio()
async def test_indexed_rows_are_readable() -> None:
    indexed = _attachment("индексированный.pdf", status="indexed")
    resolver = AttachmentReferenceResolver(repository=_FakeRepository([indexed]))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай файл")

    assert resolution.status == "resolved"
    assert resolution.attachment_id == indexed.id


@pytest.mark.asyncio()
async def test_two_files_without_a_named_referent_refuse() -> None:
    rows = [_attachment("a.pdf"), _attachment("b.pdf")]
    resolver = AttachmentReferenceResolver(repository=_FakeRepository(rows))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай этот файл")

    assert resolution.status == "ambiguous"
    assert resolution.attachment_id is None
    assert set(resolution.candidates) == {"a.pdf", "b.pdf"}


@pytest.mark.asyncio()
async def test_named_file_wins_among_several() -> None:
    target = _attachment("СФУТ 9.03-2025.pdf")
    rows = [target, _attachment("приложение.docx")]
    resolver = AttachmentReferenceResolver(repository=_FakeRepository(rows))

    resolution = await resolver.resolve(
        user_id="user-1",
        thread_id="thread-1",
        hint_text="перечитай СФУТ 9.03-2025 из БД",
    )

    assert resolution.status == "resolved"
    assert resolution.attachment_id == target.id


class _RecordingLogger:
    """Captures structlog-style ``(event, kwargs)`` pairs from the resolver."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


@pytest.mark.asyncio()
async def test_missing_thread_is_logged_instead_of_looking_like_an_empty_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a thread-less re-read produced ``no_candidates`` with no trace.

    Without the id the resolver cannot select a row at all, so an empty result read
    as "this dialog has no files" and the incident was undebuggable (055).
    """
    import palatium_ai.application.services.attachment_reference_resolver as module

    recorder = _RecordingLogger()
    monkeypatch.setattr(module, "logger", recorder)
    repository = _FakeRepository([_attachment("a.pdf")])
    resolver = AttachmentReferenceResolver(repository=repository)

    resolution = await resolver.resolve(user_id="user-1", thread_id="  ", hint_text="перечитай файл")

    assert resolution.status == "no_candidates"
    assert repository.calls == []  # never queried with a blank scope
    event, fields = recorder.events[0]
    assert event == "attachment_reference.resolve_failed"
    assert fields["reason"] == "thread_id_missing"


@pytest.mark.asyncio()
async def test_unresolved_reference_logs_counts_not_file_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics must be actionable without putting user content in logs (020)."""
    import palatium_ai.application.services.attachment_reference_resolver as module

    recorder = _RecordingLogger()
    monkeypatch.setattr(module, "logger", recorder)
    resolver = AttachmentReferenceResolver(repository=_FakeRepository([_attachment("a.pdf"), _attachment("b.pdf")]))

    resolution = await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай этот файл")

    assert resolution.status == "ambiguous"
    event, fields = recorder.events[0]
    assert event == "attachment_reference.resolve_failed"
    assert fields["thread_id"] == "thread-1"
    assert fields["reason"] == "several_thread_files"
    assert fields["candidate_count"] == 2
    assert fields["thread_file_count"] == 2
    assert "a.pdf" not in repr(fields)
    assert "b.pdf" not in repr(fields)


@pytest.mark.asyncio()
async def test_metrics_record_the_outcome_kind_without_a_new_metric_name() -> None:
    from palatium_ai.core.observability.metrics import agent_metrics

    resolver = AttachmentReferenceResolver(repository=_FakeRepository([_attachment("a.pdf")]))
    await resolver.resolve(user_id="user-1", thread_id="thread-1", hint_text="перечитай файл")

    assert (
        agent_metrics.attachment_read_count(
            kind="reference_resolved",
            ocr_applied=False,
            ocr_engine="none",
            ocr_cached=False,
        )
        >= 1
    )
