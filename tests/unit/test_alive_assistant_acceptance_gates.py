"""Acceptance gates for Alive Assistant Context Circulation 2026 (plan checklist).

Full live chat scenarios remain manual/eval; these unit gates lock the contracts
that made the assistant look blind.
"""

from __future__ import annotations

from palatium_ai.core.config.attachments import AttachmentConfig
from palatium_ai.core.observability.file_reread_rollout import resolve_file_reread
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy
from palatium_ai.domain.policies.clarification import ClarificationGatePolicy
from palatium_ai.domain.policies.researcher_observation import ResearcherObservationPolicy
from palatium_ai.domain.policies.soft_clarify import SoftClarifyPolicy


def test_acceptance_thread_file_reread_cutover_default() -> None:
    """Checklist #3: follow-up re-read is on by default (rollback = PCT=0)."""
    assert AttachmentConfig.model_fields["file_reread_pct"].default == 100
    assert resolve_file_reread(100, "any-user") is True
    assert resolve_file_reread(0, "any-user") is False


def test_acceptance_truncation_forces_jit_reread() -> None:
    """Checklist #1: middle-of-doc asks must not stay on head/tail dump alone."""
    from uuid import UUID

    from palatium_ai.domain.attachments.citations import attachment_ids_from_untrusted_context
    from palatium_ai.domain.attachments.fence_source import attachment_fence_source
    from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output

    fence = "head\n… [attachment body truncated] …\nmiddle section 3\ntail"
    assert ResearcherObservationPolicy.should_force_read_plan(attached_files=fence, already_direct_read=False)
    aid = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    fenced = wrap_untrusted_tool_output(
        fence,
        source=attachment_fence_source(attachment_id=aid, filename="doc.pdf"),
    )
    assert attachment_ids_from_untrusted_context(fenced) == (str(aid),)


def test_acceptance_soft_clarify_answerable_not_open_ask() -> None:
    """Checklist: answerable soft clarify prefers answer path."""
    assert SoftClarifyPolicy.prefer_answer_path(task_kind="knowledge_request", has_attachments=True, has_prior=False)


def test_acceptance_clarify_gate_not_punctuation_router() -> None:
    """Checklist: ClarificationGate uses axes, not endswith('?')."""
    from palatium_ai.domain.agents.intent import IntentClassifierOutput

    out = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        grounding="none",
        confidence=0.9,
        reasoning="fact ask",
    )
    # No trailing '?': still a fact ask via axes → grounding bumped on empty thread.
    gated = ClarificationGatePolicy.apply(
        out,
        has_prior_dialog=False,
        has_attachment_context=False,
        user_text="Какой протокол использует Зенит",
    )
    assert gated.grounding == "required"


def test_acceptance_multi_step_honest_collapse() -> None:
    """Checklist: multi_step is not advertised as N-step decomposition."""
    kind = WorkflowExecutionPolicy.executable_task_kind("multi_step_workflow", requires_mcp=False)
    assert kind == "knowledge_request"
    plan = WorkflowExecutionPolicy.plan_for(
        "multi_step_workflow",
        requires_mcp=False,
        default_plans={
            "knowledge_request": "single pass",
            "clarification_needed": "ask",
            "tool_execution": "tool",
            "response_formatting": "format",
            "social_conversation": "social",
            "capability_discovery": "caps",
            "multi_step_workflow": "never",
            "data_analysis": "analyst",
            "code_generation": "coder",
        },
    )
    assert "not decomposable" in plan


def test_acceptance_paste_text_does_not_mint_file_choice() -> None:
    """Live UX: chat-text paste with prior Договор_*.docx must not interrupt for re-read."""
    from uuid import uuid4

    from palatium_ai.domain.agents.intent import IntentClassifierOutput
    from palatium_ai.domain.policies.continuity import ContinuityPolicy
    from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy

    paste = (
        "1. Выдели 5 тезисов: рынок электромобилей…\n"
        "2. Перефразируй официально: система тормозит…\n"
        "3. Извлеки даты и названия: 12 апреля 2023 компания подписала договор…"
    )
    contracts = [
        FileRefCandidate(attachment_id=uuid4(), filename="Договор оказания услуг.docx"),
        FileRefCandidate(attachment_id=uuid4(), filename="Договор оказания услуг_2.docx"),
    ]
    resolution = FileReferencePolicy.resolve(contracts, hint_text=paste)
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False

    intent = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        confidence=0.9,
        reasoning="paste analysis",
        file_reference="thread_file",
        attachment_scope="single",
        attachment_focus="current_uploads",
    )
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=intent,
        user_text=paste,
        thread_file_named=False,
    )
    assert effective.file_reference == "none"


def test_acceptance_followup_topic_does_not_name_older_thread_file() -> None:
    """Live: topical follow-up after a new upload must not promote an older OCR hit."""
    from uuid import uuid4

    from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy

    sfot = FileRefCandidate(
        attachment_id=uuid4(),
        filename="СФОТ_Банки.pdf",
        search_text="Управление доступом к АБС и ролям операторов",
    )
    archive = FileRefCandidate(
        attachment_id=uuid4(),
        filename="Заявка_Госархив_Могилев.docx",
        search_text="Управление доступом к архивным документам",
    )
    resolution = FileReferencePolicy.resolve(
        [sfot, archive],
        hint_text="подробнее о Управление доступом",
    )
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False


def test_acceptance_general_ask_with_thread_files_stays_intent_driven() -> None:
    """Live: KB/general ask with prior uploads must not force a storage re-read."""
    from uuid import uuid4

    from palatium_ai.domain.agents.intent import IntentClassifierOutput
    from palatium_ai.domain.policies.continuity import ContinuityPolicy
    from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy

    files = [
        FileRefCandidate(
            attachment_id=uuid4(),
            filename="Заявка_Госархив_Могилев.docx",
            search_text="электронный документооборот и цифровая подпись",
        ),
    ]
    ask = "Как устроен электронный документооборот в общем случае?"
    resolution = FileReferencePolicy.resolve(files, hint_text=ask)
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False

    intent = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        confidence=0.9,
        reasoning="general kb",
        file_reference="thread_file",
        attachment_scope="auto",
        attachment_focus="none",
        grounding="optional",
    )
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=intent,
        user_text=ask,
        thread_file_named=False,
    )
    assert effective.file_reference == "none"
