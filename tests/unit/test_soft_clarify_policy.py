"""SoftClarifyPolicy — answerable asks must not ship as open clarify success."""

from __future__ import annotations

from palatium_ai.domain.policies.soft_clarify import SoftClarifyPolicy


def test_prefer_answer_when_attachments_or_prior() -> None:
    assert SoftClarifyPolicy.prefer_answer_path(task_kind="clarification_needed", has_attachments=True, has_prior=False)
    assert SoftClarifyPolicy.prefer_answer_path(task_kind="clarification_needed", has_attachments=False, has_prior=True)


def test_prefer_answer_for_knowledge_kinds() -> None:
    assert SoftClarifyPolicy.prefer_answer_path(task_kind="knowledge_request", has_attachments=False, has_prior=False)


def test_open_ask_for_true_clarify_without_evidence() -> None:
    assert not SoftClarifyPolicy.prefer_answer_path(task_kind="clarification_needed", has_attachments=False, has_prior=False)
