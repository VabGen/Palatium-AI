"""Frozen PlatformReadAttachmentOutput validates MCP tool payloads (070)."""

from __future__ import annotations

import json

from uuid import uuid4

from palatium_ai.application.agents.researcher.parsing import (
    parse_read_attachment_output,
    unwrap_read_attachment_text,
)
from palatium_ai.domain.mcp.platform_schemas import PlatformReadAttachmentOutput


def test_valid_envelope_parses_and_unwraps() -> None:
    aid = str(uuid4())
    payload = {
        "tool": "read_attachment",
        "attachment_id": aid,
        "filename": "scan.pdf",
        "mime_type": "application/pdf",
        "truncated": False,
        "offset": 0,
        "total_chars": 12,
        "ocr_applied": False,
        "ocr_cached": False,
        "ocr_engine": "",
        "extract_status": "ok",
        "notice": None,
        "fenced_text": "<<<ATTACHMENT:scan.pdf>>>\nhello world\n<<<END_ATTACHMENT>>>",
    }
    typed = parse_read_attachment_output(json.dumps(payload))
    assert isinstance(typed, PlatformReadAttachmentOutput)
    assert typed.attachment_id == aid
    assert unwrap_read_attachment_text(json.dumps(payload)) == "hello world"


def test_malformed_envelope_fails_open_to_raw() -> None:
    assert parse_read_attachment_output("not-json") is None
    assert unwrap_read_attachment_text("plain body") == "plain body"
