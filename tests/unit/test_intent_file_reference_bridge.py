"""The ``file_reference`` axis: Intent owns it, Continuity passes it, the bridge hints it (055)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.attachment_stickiness import AttachmentStickinessPolicy
from palatium_ai.domain.policies.continuity import ContinuityPolicy
from palatium_ai.domain.policies.types import FILE_REFERENCE_DEFAULT


def _dialog(*, with_attachment: bool) -> DialogTurnWindow:
    attachment_id = str(uuid4())
    payload: dict[str, object] = {"attachment_ids": [attachment_id]} if with_attachment else {}
    turn = DialogTurn(
        id=uuid4(),
        thread_id="thread-1",
        role="user",
        content="анализ файла СФУТ 9.03-2025",
        payload=payload,
        seq=0,
        created_at=datetime.now(UTC),
    )
    return DialogTurnWindow(thread_id="thread-1", turns=(turn,), limit=12)


def _intent(**overrides: object) -> IntentClassifierOutput:
    payload: dict[str, object] = {
        "task_kind": "knowledge_request",
        "requires_mcp": False,
        "confidence": 0.9,
        "reasoning": "test",
    }
    payload.update(overrides)
    return IntentClassifierOutput(**payload)  # type: ignore[arg-type]  # test builder (017)


def test_thread_has_files_reads_turn_payloads() -> None:
    assert AttachmentStickinessPolicy.thread_has_files(_dialog(with_attachment=True)) is True
    assert AttachmentStickinessPolicy.thread_has_files(_dialog(with_attachment=False)) is False
    assert AttachmentStickinessPolicy.thread_has_files(None) is False


def test_axis_defaults_to_none() -> None:
    assert _intent().file_reference == FILE_REFERENCE_DEFAULT


def test_parse_accepts_thread_file_only_when_the_thread_holds_files() -> None:
    raw = '{"task_kind": "knowledge_request", "requires_mcp": true, "file_reference": "thread_file", "confidence": 0.9, "reasoning": "r"}'

    with_files = parse_classifier_output(raw, has_thread_files=True)
    without_files = parse_classifier_output(raw, has_thread_files=False)

    assert with_files.file_reference == "thread_file"
    # No files in the dialog → a storage read cannot be substantiated (055).
    assert without_files.file_reference == "none"


def test_parse_ignores_an_invented_axis_value() -> None:
    raw = '{"task_kind": "knowledge_request", "requires_mcp": true, "file_reference": "minio_bucket", "confidence": 0.9, "reasoning": "r"}'

    parsed = parse_classifier_output(raw, has_thread_files=True)

    assert parsed.file_reference == "none"


def test_continuity_forces_a_worker_owned_knowledge_request_for_a_thread_file() -> None:
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=_dialog(with_attachment=True),
        raw_intent=_intent(file_reference="thread_file", task_kind="response_formatting"),
    )

    assert effective.file_reference == "thread_file"
    assert effective.task_kind == "knowledge_request"
    assert effective.requires_mcp is True


def test_continuity_keeps_none_when_no_reference_axis() -> None:
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=_dialog(with_attachment=True),
        raw_intent=_intent(requires_mcp=False),
    )

    assert effective.file_reference == "none"
    assert effective.requires_mcp is False
    assert effective.task_kind == "knowledge_request"


def test_axis_survives_a_low_risk_route_snapshot() -> None:
    """The axis is not rewritten by the social/format route machinery."""
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=_dialog(with_attachment=True),
        raw_intent=_intent(file_reference="thread_file", task_kind="knowledge_request"),
    )

    assert effective.file_reference == "thread_file"
    assert "file_reference" in effective.model_dump()
