# src/palatium_ai/domain/ports/attachment_read.py

"""Port for on-demand attachment body reads (lazy OCR / Vision via parser)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.attachments.read import AttachmentReadRequest, AttachmentReadResult


class AttachmentReadPort(Protocol):
    """Owner-scoped attachment text access for ``platform.read_attachment``.

    Implementations enforce RBAC (foreign owner → ``AttachmentNotFoundError``),
    size ceiling, derived-blob cache, and lazy ``DocumentParserPort.parse`` with
    write-through — never a separate Vision HTTP client (070, 020).
    """

    async def read(self, request: AttachmentReadRequest) -> AttachmentReadResult:
        """Return a sliced body; soft ``notice`` when OCR/Vision both fail."""
        ...


__all__ = ["AttachmentReadPort"]
