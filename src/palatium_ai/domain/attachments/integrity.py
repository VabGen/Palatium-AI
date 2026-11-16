"""Original-blob integrity: SHA-256 seal + fail-closed verify (020, W10 P0.4)."""

from __future__ import annotations

from palatium_ai.core.types.digest import SHA256_HEX_LENGTH, assert_sha256_hex_match, sha256_hex
from palatium_ai.domain.attachments.errors import AttachmentIntegrityError
from palatium_ai.domain.attachments.models import Attachment

__all__ = [
    "SHA256_HEX_LENGTH",
    "content_sha256_hex",
    "verify_attachment_bytes",
]


def content_sha256_hex(data: bytes) -> str:
    """Digest of the exact bytes stored at ``blob_key``."""
    return sha256_hex(data)


def verify_attachment_bytes(attachment: Attachment, data: bytes) -> None:
    """Fail-closed when a sealed row's blob no longer matches the stored digest.

    Legacy rows with ``content_sha256 is None`` skip verification (no silent
    backfill at read time — reingest / complete seals new uploads).
    """
    expected = attachment.content_sha256
    if expected is None:
        return
    actual = content_sha256_hex(data)
    if assert_sha256_hex_match(expected=expected, actual_hex=actual):
        return
    raise AttachmentIntegrityError(attachment.id)
