"""Golden dense analysis document (kimi-answer-formatting F5)."""

from __future__ import annotations

import json

from pathlib import Path

from palatium_ai.domain.content import ContentDocument, HeadingBlock, KeyValueBlock, ListBlock
from palatium_ai.domain.content.lint import ContentLint
from palatium_ai.domain.policies.presentation_icons import PresentationIconPolicy
from palatium_ai.domain.policies.shape import ShapeRecipePolicy

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content" / "dense_analysis.json"


def test_dense_analysis_fixture_validates_and_is_shape_dense() -> None:
    document = ContentDocument.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    headings = [block for block in document.blocks if isinstance(block, HeadingBlock)]
    assert len(headings) >= 2
    assert any(isinstance(block, KeyValueBlock) for block in document.blocks)
    assert any(isinstance(block, ListBlock) and any(item.level > 0 for item in block.items) for block in document.blocks)

    recipe = ShapeRecipePolicy.resolve(shape="document_analysis", task_kind="knowledge_request")
    assert recipe is not None
    assert ShapeRecipePolicy.validate(document, recipe).satisfied is True

    enriched = PresentationIconPolicy.enrich(document)
    assert ContentLint.run(enriched).findings == ()


def test_enrich_keeps_sparse_heading_chrome() -> None:
    """Lead + signal headings keep icons; decorative ``list`` is pruned."""
    document = ContentDocument.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    enriched = PresentationIconPolicy.enrich(document)
    headings = [block for block in enriched.blocks if isinstance(block, HeadingBlock)]
    by_text = {block.text: block.icon for block in headings}
    assert by_text["Заказчик"] == "search"
    assert by_text["Требования"] is None
    assert by_text["Риски"] == "warning"
    assert by_text["Рекомендации"] == "check"
    lists = [block for block in enriched.blocks if isinstance(block, ListBlock)]
    assert all(item.icon is None for block in lists for item in block.items)
