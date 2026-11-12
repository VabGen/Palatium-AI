"""Singular read_attachment must not leak the MCP JSON envelope (W10.2)."""

from __future__ import annotations

import json

from palatium_ai.application.agents.researcher.parsing import unwrap_read_attachment_text


def test_unwrap_extracts_body_from_envelope() -> None:
    raw = json.dumps(
        {
            "tool": "read_attachment",
            "attachment_id": "файл",
            "filename": "Скан 1_Приложение.txt",
            "fenced_text": ("<<<ATTACHMENT:Скан 1_Приложение.txt>>>\nСодержимое Скан 1: протокол ALPHA.\n<<<END_ATTACHMENT>>>"),
        },
        ensure_ascii=False,
    )
    body = unwrap_read_attachment_text(raw)
    assert body == "Содержимое Скан 1: протокол ALPHA."
    assert "fenced_text" not in body
    assert "read_attachment" not in body
    assert "<<<ATTACHMENT" not in body


def test_unwrap_passes_through_plain_text() -> None:
    assert unwrap_read_attachment_text("просто текст") == "просто текст"
