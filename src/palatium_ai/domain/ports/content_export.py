# src/palatium_ai/domain/ports/content_export.py

"""Port for rendering ``ContentDocument`` artifacts (000: application depends on ports)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.content import ContentDocument


class ContentDocumentExporterPort(Protocol):
    """Render a typed ``ContentDocument`` to downloadable bytes."""

    def export(self, document: ContentDocument) -> bytes:
        """Serialize ``document`` (e.g. PDF); implementation lives in infrastructure."""
        ...
