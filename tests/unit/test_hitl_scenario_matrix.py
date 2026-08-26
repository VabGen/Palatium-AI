"""HITL scenario matrix S1–S10 (contract coverage without live LLM).

Maps the product DoD from the universal HITL plan to unit assertions.
Live E2E (LLM + UI): scripts/smoke_hitl_choice.py, scripts/smoke_hitl_write_step_up.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from palatium_ai.application.services.interaction_assembler import InteractionAssembler
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy
from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption
from palatium_ai.domain.hitl.choice_resume import ChoiceResumePolicy
from palatium_ai.domain.hitl.escalation_policy import HitlTimeoutPolicy
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.continuity import ContinuityPolicy


def _menu_doc(items: list[str]) -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Варианты",
        blocks=(
            ParagraphBlock(type="paragraph", text="Выберите тему:"),
            ListBlock(
                type="list",
                style="unordered",
                items=tuple(ListItem(text=item, icon=None, emphasis=None) for item in items),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )


_EDMS_SEARCH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Search string for EDMS documents.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_EDMS_ARCHIVE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "document_id": {
            "type": "string",
            "minLength": 1,
            "description": "EDMS document identifier to archive.",
        },
    },
    "required": ["document_id"],
    "additionalProperties": False,
}


def test_s1_s3_options_menu_force_mints_without_intent_flag() -> None:
    """S1/S3: exclusive topic list → choice actions even if Intent forgot the flag."""
    doc = _menu_doc(
        [
            "Офисные будни",
            "Путешествия",
            "IT",
            "Семья",
            "Учёба",
            "Спорт",
            "Еда",
            "Гаджеты",
            "Медицина",
            "Погода",
        ]
    )
    assembled = InteractionAssembler.assemble(
        doc,
        requires_review=False,
        task_kind="knowledge_request",
        requires_user_choice=False,
    )
    assert assembled.invalid is False
    assert assembled.plan.force_structural is True
    assert len(assembled.plan.choice_actions) == 10
    assert assembled.strip_exclusive_menu is True
    assert assembled.document is not None
    assert all(block.type != "list" for block in assembled.document.blocks)


def test_s2_choice_resume_envelope_is_typed_not_nl() -> None:
    """S2: click → typed resume envelope (action_id), not free-text process(label)."""
    now = datetime(2099, 1, 1, tzinfo=UTC)
    card = HITLCardView(
        card_id="card_test_s2",
        thread_id="t1",
        task_id="task1",
        purpose="user_choice",
        title="Темы",
        body=None,
        options=(
            HITLOption(
                action_id="choice_1",
                label="Путешествия",
                kind="custom",
                style="primary",
                action_token="tok",
            ),
            HITLOption(
                action_id="choice_2",
                label="Работа",
                kind="custom",
                style="secondary",
                action_token="tok2",
            ),
        ),
        risk_score=0.2,
        status="pending",
        expires_at=now,
        created_at=now,
    )
    selection = ChoiceResumePolicy.selection_from_card(card, "choice_1")
    text = ChoiceResumePolicy.graph_user_text(selection)
    assert selection.action_id == "choice_1"
    assert selection.resume_kind == "clarify"
    assert "HITL_CHOICE_RESUME" in text
    assert "action_id=choice_1" in text
    assert "UNTRUSTED_HITL_LABEL" in text


def test_s4_required_choice_without_options_fails_closed() -> None:
    """S4: required choice + prose-only document → formatter_output_invalid."""
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Pick",
        blocks=(ParagraphBlock(type="paragraph", text="Choose somehow"),),
        actions=(),
        meta=DocumentMeta(
            confidence=0.9,
            requires_review=False,
            source_refs=(),
            interaction="choice",
        ),
    )
    assembled = InteractionAssembler.assemble(doc, requires_review=False, requires_user_choice=True)
    assert assembled.invalid is True
    assert assembled.plan.reason == "formatter_output_invalid"


def test_s5_archive_write_requires_hitl() -> None:
    """S5: pinned archive_document → write + requires_hitl."""
    archive = MCPToolDescriptor(
        name="archive_document",
        description="Archive",
        inputSchema=_EDMS_ARCHIVE_SCHEMA,
    )
    pin = resolve_platform_pin(archive, server_name="edms")
    assert pin is not None
    assert pin.side_effect == "write"
    assert pin.requires_hitl is True
    assert requires_interrupt_before_call(pin.side_effect, pin=pin) is True


def test_s6_unpinned_tool_is_unknown_interrupt() -> None:
    """S6: new MCP tool without pin → unknown → interrupt."""
    mystery = MCPToolDescriptor(name="delete_everything", description="", inputSchema={})
    effect = classify_side_effect(mystery, server_name="edms")
    assert effect == "unknown"
    assert requires_interrupt_before_call(effect) is True
    assert resolve_platform_pin(mystery, server_name="edms") is None


def test_s7_pinned_read_skips_interrupt() -> None:
    """S7: pinned search_documents → read, no HITL interrupt."""
    search = MCPToolDescriptor(
        name="search_documents",
        description="Search",
        inputSchema=_EDMS_SEARCH_SCHEMA,
    )
    pin = resolve_platform_pin(search, server_name="edms")
    assert pin is not None
    assert pin.side_effect == "read"
    assert pin.requires_hitl is False
    assert requires_interrupt_before_call(pin.side_effect, pin=pin) is False


def test_s8_intent_choice_then_continuity_stays_clarify() -> None:
    """S8 prelude: choice axis forces clarification before any tool path."""
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        requires_user_choice=True,
        candidate_capabilities=("summarize",),
        confidence=0.91,
        reasoning="need topic pick before joke",
    )
    normalized = UserChoiceIntentPolicy.normalize(raw)
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=normalized,
    )
    assert effective.task_kind == "clarification_needed"
    assert effective.requires_user_choice is True
    assert effective.requires_mcp is False


def test_s9_high_risk_timeout_escalates() -> None:
    """S9: risk_score > 0.5 on TTL → escalate to manager."""
    decision = HitlTimeoutPolicy.on_expiry(risk_score=0.85, manager_roles=("manager",))
    assert decision.outcome == "escalate"
    assert "manager" in decision.escalate_to_roles


def test_s10_policy_surface_for_idempotent_resolve() -> None:
    """S10: matrix notes idempotent resolve is covered by test_hitl_service.

    Guard the contract surface so the matrix stays discoverable.
    """
    assert hasattr(HitlInteractionPolicy, "plan")
    assert hasattr(InteractionAssembler, "assemble")
