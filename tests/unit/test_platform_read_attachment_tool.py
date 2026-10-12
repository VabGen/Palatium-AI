"""platform.read_attachment MCP handler + pin discovery (070)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.domain.attachments.read import AttachmentReadResult
from palatium_ai.domain.mcp.tool_policy import local_capability_tool_descriptors
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler


class _FakeKnowledge:
    pass


class _FakeRead:
    def __init__(self, result: AttachmentReadResult) -> None:
        self.result = result
        self.requests: list[object] = []

    async def read(self, request):
        self.requests.append(request)
        return self.result


@pytest.mark.asyncio()
async def test_read_attachment_fenced_payload() -> None:
    aid = uuid4()
    reader = _FakeRead(
        AttachmentReadResult(
            attachment_id=aid,
            filename="scan.pdf",
            mime_type="application/pdf",
            text="hello scan",
            ocr_applied=True,
            ocr_engine="tesseract",
            extract_status="ocr_ok",
            total_chars=10,
        )
    )
    handler = PlatformToolHandler(
        knowledge_port=_FakeKnowledge(),  # type: ignore[arg-type]
        attachment_read=reader,  # type: ignore[arg-type]
    )
    outcome = await handler.call_tool(
        "read_attachment",
        {"user_id": "u1", "attachment_id": str(aid)},
    )
    assert outcome.is_error is False
    text = outcome.content[0]["text"]
    assert "<<<ATTACHMENT:scan.pdf>>>" in text
    assert "hello scan" in text
    assert "ocr_applied" in text


def test_read_attachment_listed_in_platform_discovery() -> None:
    names = {d.name for d in local_capability_tool_descriptors("platform")}
    assert "read_attachment" in names
