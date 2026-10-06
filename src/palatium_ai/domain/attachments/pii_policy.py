# src/palatium_ai/domain/attachments/pii_policy.py

"""Attachment extracted-text PII policy tiers (G06) — pure, deterministic (055).

``tag`` — record ``contains_pii`` only (current default).
``mask`` — redact emails/phones/passport-like tokens in prompt-eligible text.
``reject`` — refuse admission with ``pii_detected`` (fail closed for sensitive corpora).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.pii import mask_pii_in_text, text_looks_like_pii

AttachmentPiiPolicyMode = Literal["tag", "mask", "reject"]


class AttachmentPiiDecision(BaseModel):
    """Outcome of applying the configured PII tier to extracted flow text."""

    model_config = {"frozen": True}

    contains_pii: bool = False
    mode: AttachmentPiiPolicyMode = "tag"
    #: When ``mask``, the redacted body for ``safe_text``; otherwise unused.
    masked_text: str | None = Field(default=None, max_length=500_000)
    refuse: bool = False


def apply_attachment_pii_policy(
    text: str,
    *,
    mode: AttachmentPiiPolicyMode = "tag",
) -> AttachmentPiiDecision:
    """Classify extracted text and optionally mask or refuse (020, 060)."""
    flagged = text_looks_like_pii(text)
    if not flagged:
        return AttachmentPiiDecision(contains_pii=False, mode=mode, refuse=False)
    if mode == "reject":
        return AttachmentPiiDecision(contains_pii=True, mode=mode, refuse=True)
    if mode == "mask":
        return AttachmentPiiDecision(
            contains_pii=True,
            mode=mode,
            masked_text=mask_pii_in_text(text),
            refuse=False,
        )
    return AttachmentPiiDecision(contains_pii=True, mode="tag", refuse=False)


__all__ = [
    "AttachmentPiiDecision",
    "AttachmentPiiPolicyMode",
    "apply_attachment_pii_policy",
]
