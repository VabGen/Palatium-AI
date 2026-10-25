"""File-choice card: ambiguous re-read → grounded options (055, 070, 020)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from palatium_ai.application.services.attachment_reference_resolver import AttachmentReferenceResolver
from palatium_ai.application.services.intent_hitl_flow import IntentHitlFlow
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.researcher import ATTACHMENT_REFERENCE_UNRESOLVED
from palatium_ai.domain.content import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption
from palatium_ai.domain.hitl.file_choice import ALL_FILES_ACTION_ID, FileChoiceCardPolicy
from palatium_ai.domain.policies.file_reference import FileReferenceResolution

_ID_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ID_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_NAMES = ("Обращение.docx", "СФОТ_Банки.pdf")


def _doc() -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Файлы диалога",
        blocks=(ParagraphBlock(type="paragraph", text="Полный текст резюме файла ответа."),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False),
    )


def _result() -> FormatterTaskResult:
    return FormatterTaskResult(
        task_id="task-1",
        agent_role="formatter",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=_doc(),
    )


class _CardService:
    """Minimal HitlService stub capturing the minted card."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_choice_card(self, **kwargs: Any) -> HITLCardView:
        self.calls.append(kwargs)
        actions = kwargs["actions"]
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return HITLCardView(
            card_id="card-file",
            thread_id=kwargs["thread_id"],
            task_id=kwargs["task_id"],
            purpose="user_choice",
            title=kwargs["title"],
            options=tuple(HITLOption(action_id=a.action_id, label=a.label, kind=a.kind, action_token="tok") for a in actions),
            risk_score=0.1,
            created_at=now,
            expires_at=now,
        )


class _Resolver:
    def __init__(self, resolution: FileReferenceResolution, explicit: FileReferenceResolution | None = None) -> None:
        self._resolution = resolution
        self._explicit = explicit
        self.resolve_calls = 0
        self.explicit_calls: list[str] = []

    async def resolve(self, **_kwargs: Any) -> FileReferenceResolution:
        self.resolve_calls += 1
        return self._resolution

    async def resolve_explicit(self, *, filename: str, **_kwargs: Any) -> FileReferenceResolution:
        self.explicit_calls.append(filename)
        return self._explicit or self._resolution


class _SessionService:
    """Session stub: HITL resume checks access and touches the session."""

    def __init__(self) -> None:
        self.patches: list[dict[str, object]] = []

    async def assert_thread_access(self, **_kwargs: Any) -> None:
        return None

    async def touch_session(self, **kwargs: Any) -> None:
        patch = kwargs.get("context_patch")
        if isinstance(patch, dict):
            self.patches.append(patch)

    async def get_session(self, **_kwargs: Any) -> None:
        return None


def _flow(resolver: _Resolver | None, card_service: Any, process_turn: Any) -> IntentHitlFlow:
    return IntentHitlFlow(
        graph_runner=AsyncMock(),  # type: ignore[arg-type]
        session_service=_SessionService(),  # type: ignore[arg-type]
        hitl_service=card_service,  # type: ignore[arg-type]
        kill_switch=AsyncMock(),  # type: ignore[arg-type]
        cost_budget=AsyncMock(),  # type: ignore[arg-type]
        process_turn=process_turn,
        file_reference_resolver=resolver,  # type: ignore[arg-type]
    )


def test_policy_actions_are_names_not_ids() -> None:
    actions = FileChoiceCardPolicy.build_actions((*_NAMES, _NAMES[0], "  "))
    assert [a.action_id for a in actions] == ["filesel_1", "filesel_2"]
    assert [a.label for a in actions] == list(_NAMES)
    assert FileChoiceCardPolicy.is_file_choice("filesel_2") is True
    assert FileChoiceCardPolicy.is_file_choice("choice_2") is False
    assert FileChoiceCardPolicy.is_file_choice("filesel_0") is False
    assert FileChoiceCardPolicy.mintable(_NAMES) is True
    assert FileChoiceCardPolicy.mintable((_NAMES[0],)) is False


def test_policy_caps_options() -> None:
    names = tuple(f"file-{index}.pdf" for index in range(12))
    assert len(FileChoiceCardPolicy.build_actions(names)) == 8


def test_all_files_option_is_recognised_and_not_a_filename() -> None:
    actions = FileChoiceCardPolicy.build_actions(_NAMES, include_all=True)

    assert actions[-1].action_id == ALL_FILES_ACTION_ID
    assert actions[-1].label == "Все файлы"
    assert FileChoiceCardPolicy.is_file_choice(ALL_FILES_ACTION_ID) is True
    assert FileChoiceCardPolicy.is_all_files(ALL_FILES_ACTION_ID) is True
    assert FileChoiceCardPolicy.is_all_files("filesel_1") is False
    # The whole-set option only exists when explicitly requested (multi-file turn).
    assert [a.action_id for a in FileChoiceCardPolicy.build_actions((_NAMES[0],))] == ["filesel_1"]


@pytest.mark.asyncio()
async def test_ambiguous_reread_mints_file_card() -> None:
    card_service = _CardService()
    resolver = _Resolver(FileReferenceResolution(status="ambiguous", reason="several_thread_files", candidates=_NAMES))
    flow = _flow(resolver, card_service, AsyncMock())

    formatted = await flow.attach_hitl_cards(
        _result(),
        thread_id="thread-1",
        task_id="task-1",
        selected_strategy="direct_tool_call",
        task_kind="knowledge_request",
        user_text="а из БД взять этот файл и еще раз прочитать",
        user_id="user-1",
        file_reference="thread_file",
        execution_error=ATTACHMENT_REFERENCE_UNRESOLVED,
    )

    assert len(formatted.hitl_cards) == 1
    card = formatted.hitl_cards[0]
    assert [option.label for option in card.options] == list(_NAMES)
    assert [option.action_id for option in card.options] == ["filesel_1", "filesel_2"]
    assert formatted.output is not None
    body = formatted.output.model_dump_json()
    assert str(_ID_A) not in body
    assert "attachment_context" not in body
    assert "несколько файлов" in body


@pytest.mark.asyncio()
async def test_resolved_reference_mints_no_file_card() -> None:
    card_service = _CardService()
    resolver = _Resolver(
        FileReferenceResolution(
            status="resolved",
            attachment_id=_ID_A,
            filename=_NAMES[0],
            candidates=(_NAMES[0],),
            reason="single_thread_file",
        )
    )
    flow = _flow(resolver, card_service, AsyncMock())

    formatted = await flow.attach_hitl_cards(
        _result(),
        thread_id="thread-1",
        task_id="task-1",
        selected_strategy="direct_tool_call",
        task_kind="knowledge_request",
        user_text="перечитай",
        user_id="user-1",
        file_reference="thread_file",
        execution_error=ATTACHMENT_REFERENCE_UNRESOLVED,
    )

    assert formatted.hitl_cards == ()
    assert card_service.calls == []


@pytest.mark.asyncio()
async def test_foreign_document_no_match_mints_no_card() -> None:
    """Offering this thread's files for a named *other* document would mislead."""
    card_service = _CardService()
    resolver = _Resolver(
        FileReferenceResolution(
            status="no_match",
            reason="names_foreign_document",
            candidates=_NAMES,
        )
    )
    flow = _flow(resolver, card_service, AsyncMock())

    formatted = await flow.attach_hitl_cards(
        _result(),
        thread_id="thread-1",
        task_id="task-1",
        selected_strategy="direct_tool_call",
        task_kind="knowledge_request",
        user_text="перечитай СФУТ 9.03-2025.pdf",
        user_id="user-1",
        file_reference="thread_file",
        execution_error=ATTACHMENT_REFERENCE_UNRESOLVED,
    )

    assert formatted.hitl_cards == ()
    assert card_service.calls == []


@pytest.mark.asyncio()
async def test_other_failures_do_not_mint_file_card() -> None:
    card_service = _CardService()
    resolver = _Resolver(FileReferenceResolution(status="ambiguous", reason="several_thread_files", candidates=_NAMES))
    flow = _flow(resolver, card_service, AsyncMock())

    formatted = await flow.attach_hitl_cards(
        _result(),
        thread_id="thread-1",
        task_id="task-1",
        selected_strategy="direct_tool_call",
        task_kind="knowledge_request",
        user_text="сколько стоит билет",
        user_id="user-1",
        file_reference="none",
        execution_error="mcp_tool_error",
    )

    assert formatted.hitl_cards == ()
    assert resolver.resolve_calls == 0


@pytest.mark.asyncio()
async def test_all_files_choice_keeps_turn_uploads_without_resolving_a_name() -> None:
    process_turn = AsyncMock(return_value=object())
    resolver = _Resolver(FileReferenceResolution(status="ambiguous", reason="several_thread_files", candidates=_NAMES))
    flow = _flow(resolver, _CardService(), process_turn)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    card = HITLCardView(
        card_id="card-file",
        thread_id="thread-1",
        task_id="task-1",
        purpose="user_choice",
        title="Какой файл нужно разобрать?",
        options=(
            HITLOption(action_id="filesel_1", label=_NAMES[0], kind="custom", action_token="tok"),
            HITLOption(action_id="filesel_2", label=_NAMES[1], kind="custom", action_token="tok"),
            HITLOption(action_id=ALL_FILES_ACTION_ID, label="Все файлы", kind="custom", action_token="tok"),
        ),
        risk_score=0.1,
        created_at=now,
        expires_at=now,
    )

    await flow.process_hitl_choice(
        thread_id="thread-1",
        action_id=ALL_FILES_ACTION_ID,
        card=card,
        user_id="user-1",
    )

    assert resolver.explicit_calls == []
    assert process_turn.await_args.kwargs["attachment_ids"] is None


def _file_card() -> HITLCardView:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return HITLCardView(
        card_id="card-file",
        thread_id="thread-1",
        task_id="task-1",
        purpose="user_choice",
        title="Выберите файл",
        options=(
            HITLOption(action_id="filesel_1", label=_NAMES[0], kind="custom", action_token="tok"),
            HITLOption(action_id="filesel_2", label=_NAMES[1], kind="custom", action_token="tok"),
        ),
        risk_score=0.1,
        created_at=now,
        expires_at=now,
    )


@pytest.mark.asyncio()
async def test_file_card_pick_binds_attachment_id_without_llm() -> None:
    process_turn = AsyncMock(return_value=object())
    resolver = _Resolver(
        FileReferenceResolution(status="ambiguous", reason="several_thread_files", candidates=_NAMES),
        explicit=FileReferenceResolution(
            status="resolved",
            attachment_id=_ID_B,
            filename=_NAMES[1],
            candidates=(_NAMES[1],),
            reason="explicit_filename",
        ),
    )
    flow = _flow(resolver, _CardService(), process_turn)

    await flow.process_hitl_choice(
        thread_id="thread-1",
        action_id="filesel_2",
        card=_file_card(),
        user_id="user-1",
    )

    assert resolver.explicit_calls == [_NAMES[1]]
    kwargs = process_turn.await_args.kwargs
    assert kwargs["attachment_ids"] == [_ID_B]


@pytest.mark.asyncio()
async def test_file_card_pick_for_deleted_file_falls_back_to_plain_turn() -> None:
    process_turn = AsyncMock(return_value=object())
    resolver = _Resolver(
        FileReferenceResolution(status="ambiguous", reason="several_thread_files", candidates=_NAMES),
        explicit=FileReferenceResolution(status="no_match", reason="explicit_filename_unmatched", candidates=_NAMES),
    )
    flow = _flow(resolver, _CardService(), process_turn)

    await flow.process_hitl_choice(
        thread_id="thread-1",
        action_id="filesel_1",
        card=_file_card(),
        user_id="user-1",
    )

    assert process_turn.await_args.kwargs["attachment_ids"] is None


@pytest.mark.asyncio()
async def test_resolve_explicit_duplicate_names_picks_newest_row() -> None:
    newest = SimpleNamespace(id=_ID_B, filename=_NAMES[0], status="ready")
    older = SimpleNamespace(id=_ID_A, filename=_NAMES[0], status="ready")
    repository = AsyncMock()
    repository.list_for_thread.return_value = [newest, older]
    resolver = AttachmentReferenceResolver(repository=repository)

    resolution = await resolver.resolve_explicit(user_id="user-1", thread_id="thread-1", filename=_NAMES[0])

    assert resolution.status == "resolved"
    assert resolution.attachment_id == _ID_B
    assert resolution.reason == "card_choice_duplicate_name_newest"


@pytest.mark.asyncio()
async def test_resolve_explicit_unmatched_name_is_fail_closed() -> None:
    repository = AsyncMock()
    repository.list_for_thread.return_value = [
        SimpleNamespace(id=_ID_A, filename=_NAMES[0], status="ready"),
        SimpleNamespace(id=_ID_B, filename=_NAMES[1], status="ready"),
    ]
    resolver = AttachmentReferenceResolver(repository=repository)

    resolution = await resolver.resolve_explicit(user_id="user-1", thread_id="thread-1", filename="Договор.pdf")

    assert resolution.status == "no_match"
    assert resolution.attachment_id is None
