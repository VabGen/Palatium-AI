"""ResearcherObservationPolicy — truncation → JIT re-read (Context Circulation 2026)."""

from __future__ import annotations

from palatium_ai.domain.policies.researcher_observation import (
    MAX_TOOL_HOPS,
    ResearcherObservationPolicy,
)


def test_truncation_marker_is_incomplete() -> None:
    assert ResearcherObservationPolicy.evidence_incomplete("head\n… [attachment body truncated] …\ntail")
    assert ResearcherObservationPolicy.evidence_incomplete("… [attachment context truncated 12000 chars] …")


def test_empty_ocr_notice_is_incomplete() -> None:
    assert ResearcherObservationPolicy.evidence_incomplete(
        'Текст не извлечён. Вызови platform.read_attachment(attachment_id="…")'
    )


def test_clean_fence_is_complete() -> None:
    assert not ResearcherObservationPolicy.evidence_incomplete("Полный текст договора без маркеров.")


def test_needs_reread_respects_hop_budget() -> None:
    fence = "… [attachment body truncated] …"
    assert ResearcherObservationPolicy.needs_tool_reread(attached_files=fence, completed_hops=0)
    assert ResearcherObservationPolicy.needs_tool_reread(attached_files=fence, completed_hops=1)
    assert not ResearcherObservationPolicy.needs_tool_reread(attached_files=fence, completed_hops=MAX_TOOL_HOPS)


def test_force_read_plan_when_truncated_and_not_already_reading() -> None:
    fence = "… [attachment body truncated] …"
    assert ResearcherObservationPolicy.should_force_read_plan(attached_files=fence, already_direct_read=False)
    assert not ResearcherObservationPolicy.should_force_read_plan(attached_files=fence, already_direct_read=True)
