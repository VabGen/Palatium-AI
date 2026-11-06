"""PresentationIconPolicy — TokenIcon fill for any answer shape."""

from __future__ import annotations

from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.content_document import (
    ActionSpec,
    CalloutBlock,
    DocumentMeta,
    HeadingBlock,
    ParagraphBlock,
)
from palatium_ai.domain.policies.presentation_icons import PresentationIconPolicy


def test_analysis_lead_heading_gets_search_icon() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(
            HeadingBlock(text="Тезисный анализ"),
            ParagraphBlock(text="Документ перечисляет объекты ИС."),
            HeadingBlock(level=2, text="Рекомендации"),
        ),
        meta=DocumentMeta(confidence=0.9, kind="analysis"),
    )
    enriched = PresentationIconPolicy.enrich(document)
    assert enriched.blocks[0].icon == "search"  # type: ignore[union-attr]
    assert enriched.blocks[2].icon is None  # type: ignore[union-attr]


def test_does_not_override_explicit_icon() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(HeadingBlock(text="Отчёт", icon="chart"),),
        meta=DocumentMeta(confidence=0.9, kind="analysis"),
    )
    enriched = PresentationIconPolicy.enrich(document)
    assert enriched.blocks[0].icon == "chart"  # type: ignore[union-attr]


def test_letter_kind_skips_heading_chrome() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(HeadingBlock(text="Уважаемый коллега"),),
        meta=DocumentMeta(confidence=0.9, kind="letter"),
    )
    enriched = PresentationIconPolicy.enrich(document)
    assert enriched.blocks[0].icon is None  # type: ignore[union-attr]


def test_callout_and_action_defaults() -> None:
    document = ContentDocument(
        locale="en-US",
        blocks=(CalloutBlock(tone="warning", body="Check the licence."),),
        actions=(ActionSpec(action_id="approve", label="Approve", kind="approve", style="primary"),),
        meta=DocumentMeta(confidence=0.5, kind="guide"),
    )
    enriched = PresentationIconPolicy.enrich(document)
    assert enriched.blocks[0].icon == "warning"  # type: ignore[union-attr]
    assert enriched.actions[0].icon == "check"
