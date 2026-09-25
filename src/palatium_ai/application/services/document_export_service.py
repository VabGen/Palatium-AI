# src/palatium_ai/application/services/document_export_service.py

"""Application facade for document export (presentation must not import infrastructure)."""

from __future__ import annotations

from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.ports.content_export import ContentDocumentExporterPort


class DocumentExportService:
    """Render ContentDocument artifacts for download."""

    def __init__(self, exporter: ContentDocumentExporterPort) -> None:
        self._exporter = exporter

    def export_pdf(self, document: ContentDocument) -> bytes:
        """Serialize a typed document to PDF bytes."""
        return self._exporter.export(document)
