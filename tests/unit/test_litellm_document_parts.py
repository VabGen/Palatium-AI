"""LiteLLM message mapping includes citeable document blocks."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.domain.llm.models import ChatMessage, DocumentPart
from palatium_ai.infrastructure.llm.litellm_adapter import _to_litellm_messages

_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_user_message_carries_document_block() -> None:
    messages = _to_litellm_messages(
        [
            ChatMessage(
                role="user",
                content="Summarise the contract.",
                document_parts=(
                    DocumentPart(attachment_id=_ID, title="contract.pdf", text="Party A pays Party B."),
                ),
            )
        ]
    )
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "Summarise the contract."}
    doc = content[1]
    assert doc["type"] == "document"
    assert doc["title"] == "contract.pdf"
    assert doc["citations"] == {"enabled": True}
    assert doc["source"]["data"] == "Party A pays Party B."
