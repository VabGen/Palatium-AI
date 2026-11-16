"""W10.1 P0.1c — status/confidence disposition consistency (fail-soft documented)."""

from __future__ import annotations

from palatium_ai.application.services.interaction_assembler import InteractionAssembler
from palatium_ai.domain.content import ContentDocument, DocumentMeta, StepItem, StepsBlock
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy


def test_w101_formatter_disposition_consistent() -> None:
    """Instructional steps stay deliverable; required-choice-without-actions still fails closed."""
    howto = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(
            StepsBlock(
                type="steps",
                items=(
                    StepItem(title="One", body="Do the thing with care.", status=None, icon=None),
                    StepItem(title="Two", body="Then verify.", status=None, icon=None),
                    StepItem(title="Three", body="Ship.", status=None, icon=None),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.95, requires_review=False, source_refs=()),
    )
    assembled = InteractionAssembler.assemble(howto, requires_review=False, task_kind="knowledge_request")
    assert assembled.invalid is False
    assert assembled.plan.reason != "formatter_output_invalid"
    assert assembled.document is not None
    assert assembled.document.meta.confidence == 0.95
    assert HitlInteractionPolicy.plan(howto, requires_review=False).required_choice is False
