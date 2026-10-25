# src/palatium_ai/domain/attachments/pii_policy.py

"""Attachment extracted-text PII policy tiers (G06) — pure, deterministic (055).

``tag`` — record ``contains_pii`` only (current default).
``mask`` — redact emails/phones/passport-like tokens in prompt-eligible text.
``reject`` — refuse admission with ``pii_detected`` (fail closed for sensitive corpora).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.core.security.pii import PiiKind, scan_pii, scrub_from_scan

AttachmentPiiPolicyMode = Literal["tag", "mask", "reject"]


class AttachmentPiiDecision(BaseModel):
    """Outcome of applying the configured PII tier to extracted flow text."""

    model_config = {"frozen": True}

    contains_pii: bool = False
    mode: AttachmentPiiPolicyMode = "tag"
    #: When ``mask``, the redacted body for ``safe_text``; otherwise unused.
    masked_text: str | None = Field(default=None, max_length=500_000)
    refuse: bool = False
    #: Detected classes — makes the intake gate observable without the value (040).
    kinds: tuple[PiiKind, ...] = ()


def apply_attachment_pii_policy(
    text: str,
    *,
    mode: AttachmentPiiPolicyMode = "tag",
) -> AttachmentPiiDecision:
    """Classify extracted text and optionally mask or refuse (020, 060)."""
    scan = scan_pii(text, profile="strict")
    if not scan.found:
        return AttachmentPiiDecision(contains_pii=False, mode=mode, refuse=False)
    if mode == "reject":
        return AttachmentPiiDecision(contains_pii=True, mode=mode, refuse=True, kinds=scan.kinds)
    if mode == "mask":
        return AttachmentPiiDecision(
            contains_pii=True,
            mode=mode,
            masked_text=scrub_from_scan(text, scan, style="bracket"),
            refuse=False,
            kinds=scan.kinds,
        )
    return AttachmentPiiDecision(contains_pii=True, mode="tag", refuse=False, kinds=scan.kinds)


__all__ = [
    "AttachmentPiiDecision",
    "AttachmentPiiPolicyMode",
    "apply_attachment_pii_policy",
]
