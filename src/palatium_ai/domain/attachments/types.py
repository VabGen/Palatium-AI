# src/palatium_ai/domain/attachments/types.py

"""Attachment axis types (010) — single source for statuses, modes and refusal reasons."""

from __future__ import annotations

from typing import Literal

# attach — ephemeral, read-only for a turn/thread, no HITL.
# index  — durable write into knowledge, irreversible, HITL-gated (020, 070).
AttachmentMode = Literal["attach", "index"]

AttachmentStatus = Literal[
    "pending",  # row created, presigned URL issued, nothing uploaded yet
    "uploaded",  # client confirmed the PUT and the object exists
    "scanning",  # AV / injection pipeline running
    "ready",  # parsed and sanitized, usable in a turn
    "quarantined",  # malware or high/critical injection signal
    "indexed",  # committed to knowledge (index mode only)
    "rejected",  # refused by policy or by the security gates
    "expired",  # TTL elapsed and the blob was reclaimed
]

# Closed vocabulary for refusals: typed reasons instead of free-text errors (010, 030).
AttachmentRejectionReason = Literal[
    "size_invalid",
    "size_exceeded",
    "mime_not_allowed",
    "extension_mismatch",
    "filename_invalid",
    "turn_limit_exceeded",
    "not_uploaded",
    "malware_detected",
    # The AV engine could not answer (unreachable/timeout). Distinct from a
    # positive infection, but still fail-closed: unscanned content never passes.
    "scan_failed",
    "injection_detected",
    # The parser refused the bytes or could not extract text (corrupt/hostile).
    "parse_failed",
    "expired",
]

__all__ = [
    "AttachmentMode",
    "AttachmentRejectionReason",
    "AttachmentStatus",
]
