# tests/unit/test_citation_source_id.py

"""Binding a citation label to an upload id (W3b-2).

``source_ref`` is a display name, and a filename is not an identity: the same name may
be attached twice, and it may belong to another thread entirely. The binding therefore
exists only where the turn's fence headers make it unambiguous (020).
"""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.domain.attachments.citations import (
    attachment_ids_by_label,
    citation_refs_from_untrusted_context,
)
from palatium_ai.domain.content.citations import CitationRef


def _fence(*, attachment_id: str | None, filename: str) -> str:
    source = f"attachment:{attachment_id}:{filename}" if attachment_id else f"attachment:{filename}"
    return f"<<<UNTRUSTED_TOOL_OUTPUT source={source}>>>\nтело документа\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


def test_single_fence_binds_its_label_to_the_upload() -> None:
    attachment_id = str(uuid4())
    text = _fence(attachment_id=attachment_id, filename="contract.pdf")

    assert attachment_ids_by_label(text) == {"contract.pdf": attachment_id}


def test_same_named_uploads_stay_distinct_and_bound() -> None:
    first, second = str(uuid4()), str(uuid4())
    text = "\n\n".join(
        [
            _fence(attachment_id=first, filename="contract.pdf"),
            _fence(attachment_id=second, filename="contract.pdf"),
        ],
    )

    labels = citation_refs_from_untrusted_context(text)
    by_label = attachment_ids_by_label(text)
    first_label = f"contract.pdf#{first[:8]}"
    second_label = f"contract.pdf#{second[:8]}"

    assert labels == (first_label, second_label)
    assert by_label == {first_label: first, second_label: second}


def test_label_collision_without_ids_is_left_unbound() -> None:
    """Legacy fences carry no id: two of them cannot be told apart, so neither binds."""
    text = "\n\n".join(
        [
            _fence(attachment_id=None, filename="contract.pdf"),
            _fence(attachment_id=None, filename="contract.pdf"),
        ],
    )

    assert attachment_ids_by_label(text) == {}


def test_turn_without_fences_binds_nothing() -> None:
    assert attachment_ids_by_label("") == {}
    assert attachment_ids_by_label("обычный текст без вложений") == {}


def test_source_id_is_not_required_of_the_provider() -> None:
    """``citations`` (and thus ``source_id``) never enters the strict provider schema."""
    from palatium_ai.domain.content import ContentDocument

    meta_schema = ContentDocument.model_json_schema()["$defs"]["DocumentMeta"]["properties"]

    assert "citations" not in meta_schema


def test_source_id_is_serialised_for_the_client() -> None:
    """Unlike ``DocumentMeta.citations``, the field itself travels on the wire."""
    attachment_id = str(uuid4())
    citation = CitationRef(source_ref="contract.pdf", quote="x", source_id=attachment_id)

    assert citation.model_dump()["source_id"] == attachment_id
