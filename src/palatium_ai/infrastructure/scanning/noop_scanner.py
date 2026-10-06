# src/palatium_ai/infrastructure/scanning/noop_scanner.py

"""Fail-open scanner for local/test environments only.

This is deliberately *not* a silent no-op: the verdict carries
``engine="disabled"``, the factory logs a warning on selection, and the wiring
layer refuses the backend outside local/test (020). Uploaded files are low-trust
input, so running without AV in staging/production is a configuration error, not
a supported mode.
"""

from __future__ import annotations

from palatium_ai.domain.ports.scanner import ScanVerdict


class DisabledScanner:
    """Returns a clean verdict without inspecting the payload."""

    async def scan(self, data: bytes, *, filename: str) -> ScanVerdict:
        """Report clean while making the absence of a scan explicit."""
        return ScanVerdict(
            clean=True,
            engine="disabled",
            reason="malware scanning disabled by configuration",
            scanned_bytes=len(data),
        )
