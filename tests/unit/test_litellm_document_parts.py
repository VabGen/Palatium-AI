"""LiteLLM message mapping for citeable document parts (provider wire format)."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.domain.llm.models import ChatMessage, DocumentPart
from palatium_ai.infrastructure.llm.litellm_adapter import _to_litellm_messages

_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _user_with_doc() -> list[ChatMessage]:
    return [
        ChatMessage(
            role="user",
            content="Summarise the contract.",
            document_parts=(DocumentPart(attachment_id=_ID, title="contract.pdf", text="Party A pays Party B."),),
        )
    ]


def test_openai_compat_gateway_emits_text_not_document_block() -> None:
    """Corporate OpenAI-compat gateways 400 on Anthropic ``type=document``."""
    messages = _to_litellm_messages(_user_with_doc(), provider="gateway")
    assert len(messages) == 1
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "Summarise the contract."}
    doc = content[1]
    assert doc["type"] == "text"
    assert doc["text"] == "[contract.pdf]\nParty A pays Party B."
    assert "document" not in {part.get("type") for part in content if isinstance(part, dict)}


def test_qwen_provider_emits_text_document_parts() -> None:
    messages = _to_litellm_messages(_user_with_doc(), provider="qwen")
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "text"


def test_anthropic_keeps_native_document_block() -> None:
    messages = _to_litellm_messages(_user_with_doc(), provider="anthropic")
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "Summarise the contract."}
    doc = content[1]
    assert doc["type"] == "document"
    assert doc["title"] == "contract.pdf"
    assert doc["citations"] == {"enabled": True}
    assert doc["source"]["data"] == "Party A pays Party B."
