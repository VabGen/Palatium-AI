# src/palatium_ai/infrastructure/analysis/disabled_attachment_analysis.py

"""Fail-closed stub until an egress-blocked notebook runtime is deployed (W6 G15)."""

from __future__ import annotations

from palatium_ai.domain.ports.attachment_analysis import (
    AttachmentAnalysisRequest,
    AttachmentAnalysisResult,
)


class DisabledAttachmentAnalysis:
    """Refuses analysis so product code cannot silently skip the sandbox (020)."""

    async def analyze(self, request: AttachmentAnalysisRequest) -> AttachmentAnalysisResult:
        del request
        msg = "attachment analysis sandbox is not enabled"
        raise RuntimeError(msg)


__all__ = ["DisabledAttachmentAnalysis"]
