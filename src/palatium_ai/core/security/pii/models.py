# src/palatium_ai/domain/pii/models.py

"""PII types shared by every boundary (020, 010).

A finding carries **positions, never the matched text**: a scan result may be logged,
counted and put into a metric label without becoming the leak it is meant to prevent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Closed list of structured PII classes the platform recognises (010). Adding a kind
#: means adding a detector *and* deciding its mask on every boundary — not an ad-hoc
#: regex at one call site (050).
PiiKind = Literal["email", "phone", "iban", "tax_id", "card", "passport"]

#: ``strict`` — classification of what gets stored (memory, attachments).
#: ``observability`` — logs/traces, where a bare 9-digit number is cheap to mask.
PiiProfile = Literal["strict", "observability"]

#: Mask vocabulary per boundary: user-facing storage text vs log text.
PiiMaskStyle = Literal["bracket", "angle"]


class PiiFinding(BaseModel):
    """One detected span: kind plus code-point offsets, never the value."""

    model_config = {"frozen": True}

    kind: PiiKind
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class PiiScan(BaseModel):
    """Scan result — safe to log verbatim (kinds and offsets only)."""

    model_config = {"frozen": True}

    findings: tuple[PiiFinding, ...] = ()
    kinds: tuple[PiiKind, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.findings)


__all__ = ["PiiFinding", "PiiKind", "PiiMaskStyle", "PiiProfile", "PiiScan"]
