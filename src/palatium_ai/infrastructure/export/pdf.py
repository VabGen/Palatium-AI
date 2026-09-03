# src/palatium_ai/infrastructure/export/pdf.py

"""PDF-рендер ContentDocument (с поддержкой Unicode)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fpdf import FPDF
from structlog import get_logger

from palatium_ai.domain.content import (
    CalloutBlock,
    ChartBlock,
    CodeBlock,
    ContentDocument,
    DividerBlock,
    FormulaBlock,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
    TableBlock,
    WidgetBlock,
)

logger = get_logger(__name__)


class ContentDocumentPdfExporter:
    """Компилирует typed blocks в PDF bytes с поддержкой Unicode."""

    def export(self, document: ContentDocument) -> bytes:
        """Сериализует ContentDocument в PDF (Unicode-шрифт)."""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=16)
        pdf.add_page()

        font_name = _register_unicode_font(pdf)
        pdf.set_font(font_name, size=12)

        if document.title:
            pdf.set_font(font_name, style="B", size=18)
            _write(pdf, document.title, line_height=10)
            pdf.ln(4)
            pdf.set_font(font_name, size=12)

        for block in document.blocks:
            _render_block(pdf, font_name, block)

        pdf.set_font(font_name, size=9)
        pdf.set_text_color(100, 100, 100)
        pdf.ln(6)
        _write(
            pdf,
            f"locale={document.locale} · confidence={document.meta.confidence:.2f}",
            line_height=5,
        )

        out = pdf.output()
        return bytes(out) if isinstance(out, (bytes, bytearray)) else str(out).encode("latin-1")


def _write(pdf: FPDF, text: str, *, line_height: float = 6) -> None:
    """Пишет абзац с возвратом к левому краю."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, line_height, text, new_x="LMARGIN", new_y="NEXT")


def _render_block(pdf: FPDF, font_name: str, block: object) -> None:
    """Диспетчер блоков PDF."""
    handlers = (
        _render_heading,
        _render_paragraph,
        _render_list,
        _render_table,
        _render_callout,
        _render_code,
        _render_formula,
        _render_kv,
        _render_steps,
        _render_chart,
        _render_divider,
        _render_widget,
    )
    for handler in handlers:
        if handler(pdf, font_name, block):
            return


def _render_heading(pdf: FPDF, font_name: str, block: object) -> bool:
    if not isinstance(block, HeadingBlock):
        return False
    size = {1: 16, 2: 14, 3: 12}[block.level]
    pdf.set_font(font_name, style="B", size=size)
    _write(pdf, block.text, line_height=8)
    pdf.ln(2)
    pdf.set_font(font_name, size=12)
    return True


def _render_paragraph(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, ParagraphBlock):
        return False
    _write(pdf, block.text)
    pdf.ln(2)
    return True


def _render_list(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, ListBlock):
        return False
    for index, item in enumerate(block.items, start=1):
        prefix = f"{index}." if block.style == "ordered" else "-"
        emphasis = f"{item.emphasis} - " if item.emphasis else ""
        _write(pdf, f"{prefix} {emphasis}{item.text}")
    pdf.ln(2)
    return True


def _render_table(pdf: FPDF, font_name: str, block: object) -> bool:
    if not isinstance(block, TableBlock):
        return False
    col_w = pdf.epw / max(len(block.columns), 1)
    pdf.set_font(font_name, style="B", size=11)
    pdf.set_x(pdf.l_margin)
    for col in block.columns:
        pdf.cell(col_w, 8, col[:40], border=1)
    pdf.ln()
    pdf.set_font(font_name, size=10)
    for row in block.rows:
        pdf.set_x(pdf.l_margin)
        for cell in row:
            pdf.cell(col_w, 8, str(cell)[:40], border=1)
        pdf.ln()
    pdf.ln(2)
    pdf.set_font(font_name, size=12)
    return True


def _render_callout(pdf: FPDF, font_name: str, block: object) -> bool:
    if not isinstance(block, CalloutBlock):
        return False
    title = f"[{block.tone}] {block.title}: " if block.title else f"[{block.tone}] "
    pdf.set_font(font_name, style="B", size=11)
    _write(pdf, title + block.body)
    pdf.set_font(font_name, size=12)
    pdf.ln(2)
    return True


def _render_code(pdf: FPDF, font_name: str, block: object) -> bool:
    if not isinstance(block, CodeBlock):
        return False
    pdf.set_font(font_name, size=9)
    _write(pdf, f"[{block.language}]\n{block.content}", line_height=5)
    pdf.set_font(font_name, size=12)
    pdf.ln(2)
    return True


def _render_formula(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, FormulaBlock):
        return False
    _write(pdf, f"Formula: {block.latex}")
    pdf.ln(2)
    return True


def _render_kv(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, KeyValueBlock):
        return False
    for item in block.items:
        _write(pdf, f"{item.label}: {item.value}")
    pdf.ln(2)
    return True


def _render_steps(pdf: FPDF, font_name: str, block: object) -> bool:
    if not isinstance(block, StepsBlock):
        return False
    for index, item in enumerate(block.items, start=1):
        pdf.set_font(font_name, style="B", size=12)
        _write(pdf, f"{index}. {item.title} ({item.status})")
        pdf.set_font(font_name, size=11)
        _write(pdf, item.body)
        pdf.ln(1)
    pdf.set_font(font_name, size=12)
    pdf.ln(2)
    return True


def _render_chart(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, ChartBlock):
        return False
    title = block.title or "Chart"
    labels = ", ".join(block.labels)
    _write(pdf, f"{title} [{block.kind}]: {labels}")
    for series in block.series:
        values = ", ".join(str(v) for v in series.values)
        _write(pdf, f"  {series.name}: {values}")
    pdf.ln(2)
    return True


def _render_divider(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, DividerBlock):
        return False
    pdf.ln(2)
    pdf.set_x(pdf.l_margin)
    pdf.cell(0, 0, "", border="T")
    pdf.ln(4)
    return True


def _render_widget(pdf: FPDF, font_name: str, block: object) -> bool:
    _ = font_name
    if not isinstance(block, WidgetBlock):
        return False
    _write(pdf, f"Widget {block.kind}: {block.title or block.ref_id}")
    pdf.ln(2)
    return True


# ---- Шрифт ----
@lru_cache(maxsize=1)
def _font_path() -> Path | None:
    """Поиск Unicode-шрифта в проекте или системе."""
    project_font = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
    if project_font.is_file():
        return project_font

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _register_unicode_font(pdf: FPDF) -> str:
    path = _font_path()
    if path is None:
        logger.warning("Unicode font not found. Using Helvetica (Cyrillic will not render).")
        return "Helvetica"
    try:
        pdf.add_font("DocSans", fname=str(path))
        pdf.add_font("DocSans", style="B", fname=str(path))
        logger.debug("Unicode font registered", font_path=str(path))
        return "DocSans"
    except Exception as e:
        logger.error("Failed to register font", error=str(e))
        raise RuntimeError(f"Failed to load font from {path}. Please ensure the font file is valid.") from e
