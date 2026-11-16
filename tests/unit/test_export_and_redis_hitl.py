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
    StepItem,
    StepsBlock,
)
from palatium_ai.domain.hitl.cards import HITLCardView, default_review_options
from palatium_ai.infrastructure.export.pdf import ContentDocumentPdfExporter, _render_steps
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


class _RecordingPdf:
    """Минимальный двойник FPDF: собирает всё, что экспорт пишет на страницу."""

    l_margin = 10.0

    def __init__(self) -> None:
        self.texts: list[str] = []

    def set_font(self, family: str, *, style: str = "", size: int) -> None:
        _ = (family, style, size)

    def set_x(self, x: float) -> None:
        _ = x

    def multi_cell(self, w: float, h: float, text: str, **kwargs: object) -> None:
        _ = (w, h, kwargs)
        self.texts.append(text)

    def ln(self, h: float = 1) -> None:
        _ = h


def test_pdf_steps_omit_absent_status() -> None:
    """Шаг без состояния печатается без «(None)» — экспорт не выдумывает статус."""
    pdf = _RecordingPdf()
    block = StepsBlock(
        items=(
            StepItem(title="Подготовка", body="Собрать документы"),
            StepItem(title="Проверка", body="Сверить суммы", status="done"),
        )
    )

    assert _render_steps(pdf, "DejaVu", block) is True  # type: ignore[arg-type]

    assert pdf.texts[0] == "1. Подготовка"
    assert pdf.texts[2] == "2. Проверка (done)"


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


@pytest.mark.asyncio()
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
