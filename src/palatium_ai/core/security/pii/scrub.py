# src/palatium_ai/domain/pii/scrub.py

"""Scan and mask PII through one registry (020) — the only entry point for callers.

``scrub_pii`` is not a second implementation beside ``scan_pii``: it splices the spans
the scan produced, so the masked text and the reported findings can never disagree.
"""

from __future__ import annotations

from palatium_ai.core.security.pii.detectors import detectors_for, placeholder_for
from palatium_ai.core.security.pii.models import PiiFinding, PiiKind, PiiMaskStyle, PiiProfile, PiiScan


def scan_pii(text: str, *, profile: PiiProfile = "strict") -> PiiScan:
    """Locate structured PII; findings carry offsets, never values."""
    if not text:
        return PiiScan()
    findings: list[PiiFinding] = []
    claimed: list[tuple[int, int]] = []
    # Detector declaration order is precedence; a later detector cannot re-claim an
    # overlapping span (otherwise "УНП 123456789" would also be reported as a phone).
    for detector in detectors_for(profile):
        for start, end in detector.matches(text):
            if any(start < other_end and other_start < end for other_start, other_end in claimed):
                continue
            findings.append(PiiFinding(kind=detector.kind, start=start, end=end))
            claimed.append((start, end))
    findings.sort(key=lambda finding: finding.start)
    kinds: list[PiiKind] = []
    for finding in findings:
        if finding.kind not in kinds:
            kinds.append(finding.kind)
    return PiiScan(findings=tuple(findings), kinds=tuple(kinds))


def contains_pii(text: str, *, profile: PiiProfile = "strict") -> bool:
    return scan_pii(text, profile=profile).found


def scrub_pii(
    text: str,
    *,
    profile: PiiProfile = "strict",
    style: PiiMaskStyle = "bracket",
) -> str:
    """Replace every detected span with its boundary-appropriate placeholder."""
    return scrub_from_scan(text, scan_pii(text, profile=profile), style=style)


def scrub_from_scan(text: str, scan: PiiScan, *, style: PiiMaskStyle = "bracket") -> str:
    """Mask text using an already computed scan — callers that also classify pay once."""
    if not scan.findings:
        return text
    pieces: list[str] = []
    cursor = 0
    for finding in scan.findings:
        pieces.append(text[cursor : finding.start])
        pieces.append(placeholder_for(finding.kind, style))
        cursor = finding.end
    pieces.append(text[cursor:])
    return "".join(pieces)


__all__ = ["contains_pii", "scan_pii", "scrub_from_scan", "scrub_pii"]
