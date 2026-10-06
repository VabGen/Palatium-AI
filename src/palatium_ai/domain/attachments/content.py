# src/palatium_ai/domain/attachments/content.py

"""Derived attachment content: what survived the security pipeline (020, 065).

The blob store keeps the original bytes untouched; this envelope keeps the
*reviewed* text, so a later dialog turn rebuilds the prompt block from content
that already passed the AV and injection gates instead of re-reading the raw
upload. ``safe_text`` is the only prompt-eligible body: for ``allow`` it is the
page-addressed extraction, for ``mask`` it is the redacted flow text, and for
``quarantine``/``reject`` no envelope is persisted at all (fail closed).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import UntrustedContentAction
from palatium_ai.domain.ports.document_parser import ParsedPage


class AttachmentScanSummary(BaseModel):
    """Bounded, log-safe summary of the injection decision (never the payload)."""

    model_config = {"frozen": True}

    action: UntrustedContentAction
    worst_severity: str = Field(default="none", max_length=16)
    matched_rules: tuple[str, ...] = ()
    truncated: bool = False


class AttachmentContent(BaseModel):
    """Persisted derived text for one attachment, ready to be fenced."""

    model_config = {"frozen": True}

    pages: tuple[ParsedPage, ...] = ()
    scan: AttachmentScanSummary
    #: Prompt-eligible body. Empty for quarantine/reject (those never persist).
    #: ``allow`` keeps the page-addressed extraction (citations work verbatim);
    #: ``mask`` stores the redacted flow text, because redaction spans are
    #: computed on the marker-free view.
    safe_text: str = ""
    page_count: int = Field(default=0, ge=0)
    #: Extraction hit the parser's char/page cap, so the tail was not reviewed.
    truncated: bool = False

    @property
    def is_prompt_eligible(self) -> bool:
        """True only for the two actions that may reach a model (020)."""
        return self.scan.action in ("allow", "mask") and bool(self.safe_text)


__all__ = ["AttachmentContent", "AttachmentScanSummary"]
