# src/palatium_ai/presentation/api/routers/documents.py

"""Экспорт ContentDocument в PDF."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from palatium_ai.domain.content import ContentDocument
from palatium_ai.infrastructure.export.pdf import ContentDocumentPdfExporter
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal
from palatium_ai.presentation.security.ownership import load_session_for_principal

router = APIRouter()
_exporter = ContentDocumentPdfExporter()


class PdfExportRequest(BaseModel):
    """PDF export bound to an owned conversation thread."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    document: ContentDocument


@router.post("/export/pdf")
async def export_content_document_pdf(body: PdfExportRequest, request: Request) -> Response:
    """Рендерит typed document в PDF after session ownership check."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )
    pdf_bytes = _exporter.export(body.document)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(body.document.title)},
    )


def _content_disposition(title: str | None) -> str:
    """ASCII filename= + RFC 5987 filename* (кириллица безопасна для HTTP headers)."""
    display = _safe_download_stem(title)
    ascii_name = _ascii_filename(display)
    utf8_name = quote(f"{display}.pdf", safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


def _safe_download_stem(title: str | None) -> str:
    if not title:
        return "palatium-answer"
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in title)
    cleaned = cleaned.strip().replace(" ", "-")[:60]
    return cleaned or "palatium-answer"


def _ascii_filename(stem: str) -> str:
    ascii_stem = "".join(ch if ord(ch) < 128 and (ch.isalnum() or ch in "-_") else "" for ch in stem)
    ascii_stem = ascii_stem.strip("-_") or "palatium-answer"
    return f"{ascii_stem[:60]}.pdf"
