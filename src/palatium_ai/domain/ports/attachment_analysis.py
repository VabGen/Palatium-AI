# src/palatium_ai/domain/ports/attachment_analysis.py

"""Optional sandboxed analysis of attachment blobs (W6 G15 — ChatGPT ADA parity).

Not wired to Coder by default. A future adapter mounts the owned blob into an
egress-blocked notebook and returns structured tables/charts. HITL is required
before any execution (020).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class AttachmentAnalysisRequest(BaseModel):
    """Inputs for one sandboxed analysis job."""

    model_config = {"frozen": True}

    attachment_id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=4_000)
    filename: str = Field(default="", max_length=255)
    mime_type: str = Field(default="", max_length=128)
    data: bytes = Field(default=b"")


class AttachmentAnalysisResult(BaseModel):
    """Structured outcome; never raw interpreter stdout without fencing."""

    model_config = {"frozen": True}

    summary: str = Field(max_length=8_000)
    tables_json: str = Field(default="[]", max_length=100_000)
    charts_json: str = Field(default="[]", max_length=100_000)


class AttachmentAnalysisPort(Protocol):
    """Execute analysis in an isolated runtime with no network egress."""

    async def analyze(self, request: AttachmentAnalysisRequest) -> AttachmentAnalysisResult:
        """Run the job; implementations must fail closed when the sandbox is off."""
        ...


__all__ = [
    "AttachmentAnalysisPort",
    "AttachmentAnalysisRequest",
    "AttachmentAnalysisResult",
]
