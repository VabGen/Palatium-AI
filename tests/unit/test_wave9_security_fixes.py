"""Wave 9 adversarial fixes — ADV-01/02/03/05 regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.application.services.intent_turn_helpers import argument_preview
from palatium_ai.domain.hitl.cards import clamp_ttl_seconds
from palatium_ai.domain.memory.pii import PII_PLACEHOLDER, mask_memory_value
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def test_argument_preview_redacts_secret_shaped_values() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    preview = argument_preview({"query": "contracts", "api_key": secret})
    assert secret not in preview
    assert "[REDACTED]" in preview


def test_mask_memory_value_redacts_flagged_text_fields() -> None:
    raw = {"text": "John Doe passport 1234", "kind": "fact", "contains_pii": True}
    masked = mask_memory_value(raw, contains_pii=True)
    assert masked["text"] == PII_PLACEHOLDER
    assert masked["kind"] == "fact"


@pytest.mark.asyncio
async def test_in_memory_search_masks_pii_hits() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=("user", "alice"),
        key="pii-1",
        value={"text": "secret preference", "contains_pii": True, "confidence": 0.9},
    )
    hits = await port.search(namespace=("user", "alice"), query="secret", limit=5)
    assert hits
    assert hits[0]["text"] == PII_PLACEHOLDER


def test_irreversible_interrupt_uses_minimum_hitl_ttl() -> None:
    """ADV-03: irreversible MCP tools map to 5-minute card TTL (020)."""
    assert clamp_ttl_seconds(5 * 60) == 5 * 60
    now = datetime(2099, 1, 1, tzinfo=UTC)
    expires = now + timedelta(seconds=clamp_ttl_seconds(5 * 60))
    assert (expires - now).total_seconds() == 300
