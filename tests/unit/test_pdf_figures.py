# tests/unit/test_pdf_figures.py

"""PDF figure-page selection and caption merge (G14)."""

from __future__ import annotations

from palatium_ai.domain.attachments.pdf_figures import (
    PdfFigurePageCandidate,
    merge_figure_caption,
    select_figure_pages,
)


def test_select_figure_pages_respects_min_images_and_cap() -> None:
    candidates = (
        PdfFigurePageCandidate(page_number=1, image_count=0),
        PdfFigurePageCandidate(page_number=2, image_count=2),
        PdfFigurePageCandidate(page_number=3, image_count=1),
        PdfFigurePageCandidate(page_number=4, image_count=3),
    )
    assert select_figure_pages(candidates, max_pages=2) == (2, 3)


def test_merge_figure_caption_appends_fence() -> None:
    merged = merge_figure_caption(page_text="Intro text", caption="Bar chart of Q1 sales")
    assert "Intro text" in merged
    assert "[figure]" in merged
    assert "Bar chart of Q1 sales" in merged
    assert merge_figure_caption(page_text="x", caption="  ") == "x"
