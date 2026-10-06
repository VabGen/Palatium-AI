"""Session sticky pending_attachment_ids for HITL resume."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.application.services.intent_turn_helpers import (
    parse_pending_attachment_ids,
    serialize_pending_attachment_ids,
)


def test_roundtrip_pending_attachment_ids() -> None:
    ids = (
        UUID("73782a26-1ea4-4cb7-adf0-670a9a997bac"),
        UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    )
    encoded = serialize_pending_attachment_ids(ids)
    assert parse_pending_attachment_ids(encoded) == list(ids)


def test_parse_skips_invalid_tokens() -> None:
    assert parse_pending_attachment_ids("not-a-uuid,73782a26-1ea4-4cb7-adf0-670a9a997bac") == [
        UUID("73782a26-1ea4-4cb7-adf0-670a9a997bac")
    ]
    assert parse_pending_attachment_ids(None) == []
    assert parse_pending_attachment_ids("") == []
