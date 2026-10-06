# src/palatium_ai/domain/ports/scanner.py

"""Port for the deterministic malware verdict taken before any LLM sees a file (020).

Named ``MalwareScannerPort`` because the platform has several unrelated scanners
(secret scanner, prompt-injection scanner); this one is the AV boundary.

The prompt-injection scan deliberately has **no** port here: it is a pure
in-process function, and ports exist only for I/O boundaries (000).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ScanVerdict(BaseModel):
    """Typed antivirus verdict; ``reason`` and ``signature`` are safe for audit logs."""

    model_config = {"frozen": True}

    clean: bool
    engine: str = Field(min_length=1, max_length=64)
    # ``failed`` separates "engine says infected" from "engine could not answer".
    # Both block the payload, but only one is evidence of malice (020).
    failed: bool = False
    reason: str | None = Field(default=None, max_length=256)
    signature: str | None = Field(default=None, max_length=256)
    scanned_bytes: int = Field(default=0, ge=0)

    @property
    def infected(self) -> bool:
        """True only when the engine positively identified a threat.

        This is *evidence of malice*, never the admission gate: an unreachable
        engine also yields ``clean=False``, so a caller branching on ``infected``
        would admit unscanned content. Branch on :attr:`admitted` instead (020).
        """
        return not self.clean and not self.failed

    @property
    def admitted(self) -> bool:
        """The single fail-closed gate: only a positive clean verdict admits (020)."""
        return self.clean and not self.failed


class MalwareScannerPort(Protocol):
    """Async AV boundary; adapters must not block the event loop (050).

    Implementations return a verdict and never raise on a detected infection;
    an unreachable engine is reported as ``clean=False, failed=True`` so the
    caller fails closed instead of admitting unscanned content.
    """

    async def scan(self, data: bytes, *, filename: str) -> ScanVerdict:
        """Scan bytes and return a verdict."""
        ...
