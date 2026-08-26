"""PDF export + Redis HITL store unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.cards import HITLCardView, default_review_options
from palatium_ai.infrastructure.export.pdf import ContentDocumentPdfExporter
from palatium_ai.infrastructure.hitl.redis_store import RedisHitlCardStore
from palatium_ai.presentation.api.routers.documents import _content_disposition


def test_content_disposition_supports_cyrillic_title() -> None:
    header = _content_disposition("Привет")
    # Starlette encodes headers as latin-1 — must not raise
    header.encode("latin-1")
    assert 'filename="palatium-answer.pdf"' in header
    assert "filename*=UTF-8''" in header
    assert "%D0%9F" in header  # URL-encoded Cyrillic


def _sample_document() -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="План встречи",
        blocks=(
            HeadingBlock(type="heading", level=2, text="План встречи", icon="calendar"),
            ParagraphBlock(type="paragraph", text="Короткое введение."),
            ListBlock(
                type="list",
                style="ordered",
                items=(
                    ListItem(text="Собрать детали", icon="edit", emphasis="Шаг 1"),
                    ListItem(text="Отправить приглашения", icon="mail", emphasis=None),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )


def test_pdf_export_produces_pdf_header() -> None:
    pdf = ContentDocumentPdfExporter().export(_sample_document())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 200


class _FakePipeline:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self._ops: list[tuple[str, str, bytes, int | None]] = []

    def set(self, key: str, value: Any, ex: int | None = None) -> _FakePipeline:
        raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
        self._ops.append(("set", key, raw, ex))
        return self

    async def execute(self) -> list[bool]:
        for op, key, raw, _ex in self._ops:
            if op == "set":
                self._store[key] = raw
        self._ops.clear()
        return [True]


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self.data)

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)


@pytest.mark.asyncio
async def test_redis_hitl_store_roundtrip() -> None:
    fake = _FakeRedis()
    store = RedisHitlCardStore(fake)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    card = HITLCardView(
        card_id="hitl_test1",
        thread_id="thread-1",
        task_id="task-1",
        title="Review",
        body="Please confirm",
        options=default_review_options(),
        risk_score=0.7,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    await store.save(card, idempotency_key="idem-key-12345678")
    loaded = await store.get(card.card_id)
    assert loaded is not None
    assert loaded.card_id == card.card_id
    assert loaded.title == "Review"
    assert await store.get_idempotency_key(card.card_id) == "idem-key-12345678"
