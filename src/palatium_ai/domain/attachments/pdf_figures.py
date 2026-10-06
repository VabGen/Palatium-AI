# src/palatium_ai/domain/attachments/pdf_figures.py

"""Pure rules for when a text-layer PDF still needs a VLM figure pass (G14).

A page with a usable text layer can still contain charts/diagrams that OCR would
mangle and that pypdf cannot describe. Thresholds live here so routing stays
unit-testable without PyMuPDF (055).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Minimum rasterizable image objects on a page before we spend a vision call.
DEFAULT_MIN_IMAGES_FOR_FIGURE_PASS = 1

#: Soft cap on figure pages per document (cost / latency guard).
DEFAULT_MAX_FIGURE_PAGES = 8


class PdfFigurePageCandidate(BaseModel):
    """One page that may hold non-text visual content worth a VLM pass."""

    model_config = {"frozen": True}

    page_number: int = Field(ge=1)
    image_count: int = Field(ge=0)


def select_figure_pages(
    candidates: tuple[PdfFigurePageCandidate, ...],
    *,
    min_images: int = DEFAULT_MIN_IMAGES_FOR_FIGURE_PASS,
    max_pages: int = DEFAULT_MAX_FIGURE_PAGES,
) -> tuple[int, ...]:
    """Return 1-based page numbers that should receive a vision figure pass."""
    if max_pages <= 0 or min_images <= 0:
        return ()
    selected: list[int] = []
    for candidate in candidates:
        if candidate.image_count < min_images:
            continue
        selected.append(candidate.page_number)
        if len(selected) >= max_pages:
            break
    return tuple(selected)


def merge_figure_caption(*, page_text: str, caption: str) -> str:
    """Append a fenced figure note without erasing the text layer."""
    body = caption.strip()
    if not body:
        return page_text
    note = f"[figure]\n{body}\n[/figure]"
    base = page_text.rstrip()
    if not base:
        return note
    return f"{base}\n\n{note}"


__all__ = [
    "DEFAULT_MAX_FIGURE_PAGES",
    "DEFAULT_MIN_IMAGES_FOR_FIGURE_PASS",
    "PdfFigurePageCandidate",
    "merge_figure_caption",
    "select_figure_pages",
]
