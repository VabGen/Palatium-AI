# src/palatium_ai/domain/pii/__init__.py

"""Structured PII detection — one registry, one mask vocabulary per boundary (020)."""

from palatium_ai.core.security.pii.models import PiiFinding, PiiKind, PiiMaskStyle, PiiProfile, PiiScan
from palatium_ai.core.security.pii.scrub import contains_pii, scan_pii, scrub_from_scan, scrub_pii

__all__ = [
    "PiiFinding",
    "PiiKind",
    "PiiMaskStyle",
    "PiiProfile",
    "PiiScan",
    "contains_pii",
    "scan_pii",
    "scrub_from_scan",
    "scrub_pii",
]
