# src/palatium_ai/application/services/memory_mutation.py

"""Interactive memory mutations from chat: read check → HITL card (020/060/070).

An explicit «запомни …» / «забудь …» turn is an execution, not a question: the
platform must never answer it with prose success. This gate resolves the target
entry in medium memory (read only), stages the mutation through
``MemorySaveService`` / ``MemoryForgetService`` and returns the turn's answer with
the approval card attached. The MCP write runs only after the human approves
(``HitlRespondFacade`` dispatches the ``mem-save-`` / ``mem-forget-`` task id).

No LLM is involved after Intent: the payload is already classified, and the card
preview shows exactly what will be written or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from palatium_ai.application.services.hitl_service import HitlInvalidActionError
from palatium_ai.application.services.intent_turn_helpers import write_audit
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock, ParagraphBlock
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.policies.memory_mutation import (
    INTERACTIVE_NAMESPACE_KIND,
    MEMORY_KEY_PREFIX,
    MemoryMutationPolicy,
)
from palatium_ai.domain.policies.types import MemoryMutationKind

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_forget_service import MemoryForgetService
    from palatium_ai.application.services.memory_save_service import MemorySaveService
    from palatium_ai.domain.hitl.cards import HITLCardView
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

#: How many medium entries the read check may inspect before picking a target.
_MUTATION_SEARCH_LIMIT = 8
#: A staged mutation has no answer yet (human pending); a deterministic refusal is final.
_PENDING_CONFIDENCE = 0.0
_REFUSAL_CONFIDENCE = 1.0


@dataclass(frozen=True, slots=True)
class _Copy:
    """User-facing strings, one language at a time (locale is a presentation axis)."""

    locale: str
    save_title: str
    save_body: str
    save_update_note: str
    forget_title: str
    forget_body: str
    forget_missing_title: str
    forget_missing_body: str
    unparsed_title: str
    unparsed_body: str
    unavailable_title: str
    unavailable_body: str


_COPY_RU = _Copy(
    locale="ru",
    save_title="Нужно подтверждение записи в память",
    save_body="Сохраню «{text}» в вашу память после подтверждения карточки.",
    save_update_note="Обновлю сохранённое значение: «{existing}».",
    forget_title="Нужно подтверждение удаления из памяти",
    forget_body="Удалю из памяти «{existing}» после подтверждения карточки.",
    forget_missing_title="В памяти ничего не нашлось",
    forget_missing_body="По запросу «{text}» в вашей памяти нет записи — удалять нечего. Уточните, что именно забыть.",
    unparsed_title="Не понял, что изменить в памяти",
    unparsed_body="Сформулируйте факт для запоминания или предмет для удаления — и я подготовлю подтверждение.",
    unavailable_title="Мутация памяти недоступна",
    unavailable_body="Не удалось подготовить подтверждение ({reason}). Запись не выполнена.",
)

_COPY_EN = _Copy(
    locale="en",
    save_title="Memory write needs approval",
    save_body="I will store “{text}” in your memory once you approve the card.",
    save_update_note="This replaces the stored value: “{existing}”.",
    forget_title="Memory deletion needs approval",
    forget_body="I will delete “{existing}” from your memory once you approve the card.",
    forget_missing_title="Nothing matched in memory",
    forget_missing_body="No stored entry matches “{text}” — there is nothing to delete. Name the fact to forget.",
    unparsed_title="Nothing to change in memory",
    unparsed_body="State the fact to remember or the subject to delete, and I will prepare the approval.",
    unavailable_title="Memory mutation unavailable",
    unavailable_body="Could not prepare the approval ({reason}). Nothing was written.",
)


def _copy_for(locale: str) -> _Copy:
    """Cyrillic replies get the Russian copy; everything else the English one."""
    family = ReplyLocalePolicy.locale_script_family(locale)
    return _COPY_RU if family in {"cyrillic", "weak", "other"} else _COPY_EN


class MemoryMutationGate:
    """Deterministic owner-scoped memory mutation for one chat turn."""

    def __init__(
        self,
        *,
        save_service: MemorySaveService,
        forget_service: MemoryForgetService,
        memory_port: MemoryPort,
    ) -> None:
        self._save = save_service
        self._forget = forget_service
        self._memory = memory_port

    @traceable(name="memory_mutation.handle")
    async def handle(
        self,
        *,
        task_id: str,
        thread_id: str,
        user_id: str,
        org_id: str | None,
        kind: MemoryMutationKind,
        text: str,
        key: str,
        locale: str,
    ) -> FormatterTaskResult:
        """Stage the mutation for ``kind``; always returns the turn's final answer."""
        copy = _copy_for(locale)
        statement = MemoryMutationPolicy.coerce_text(text)
        if kind == "none" or not statement:
            return self._result(
                task_id=task_id,
                copy=copy,
                title=copy.unparsed_title,
                body=copy.unparsed_body,
                status="failure",
                error="memory_mutation_unparsed",
            )
        if not user_id.strip() or not thread_id.strip():
            return self._refusal_unavailable(task_id=task_id, copy=copy, reason="no authenticated owner")

        hits = await self._read_check(user_id=user_id, statement=statement)
        if kind == "save":
            return await self._stage_save(
                task_id=task_id,
                thread_id=thread_id,
                user_id=user_id,
                org_id=org_id,
                key=key,
                statement=statement,
                hits=hits,
                copy=copy,
            )
        return await self._stage_forget(
            task_id=task_id,
            thread_id=thread_id,
            user_id=user_id,
            org_id=org_id,
            key=key,
            statement=statement,
            hits=hits,
            copy=copy,
        )

    async def _stage_save(
        self,
        *,
        task_id: str,
        thread_id: str,
        user_id: str,
        org_id: str | None,
        key: str,
        statement: str,
        hits: list[dict[str, object]],
        copy: _Copy,
    ) -> FormatterTaskResult:
        existing = MemoryMutationPolicy.best_existing_match(hits, text=statement)
        memory_key = MemoryMutationPolicy.coerce_key(key, text=statement)
        note = ""
        if existing is not None:
            # Same subject seen before → update that entry instead of adding a second
            # contradictory fact (060: reconsolidation, not append-only memory).
            memory_key = str(existing.get("_entry_key") or "").strip() or memory_key
            stored_text = str(existing.get("text") or "").strip()
            if stored_text and stored_text != statement:
                note = copy.save_update_note.format(existing=stored_text[:200])
        try:
            card = await self._save.request_save(
                thread_id=thread_id,
                owner_user_id=user_id,
                org_id=org_id,
                namespace_kind=INTERACTIVE_NAMESPACE_KIND,
                scope_id=user_id,
                entry_key=memory_key,
                text=statement,
                memory_type="fact",
            )
        except (ValueError, HitlInvalidActionError) as exc:
            logger.warning("memory_mutation.save_unavailable", task_id=task_id, error=str(exc))
            return self._refusal_unavailable(task_id=task_id, copy=copy, reason=str(exc))
        await self._audit(task_id=task_id, thread_id=thread_id, kind="save", card=card, entry_key=memory_key)
        return self._result(
            task_id=task_id,
            copy=copy,
            title=copy.save_title,
            body=copy.save_body.format(text=statement),
            detail=note,
            card=card,
        )

    async def _stage_forget(
        self,
        *,
        task_id: str,
        thread_id: str,
        user_id: str,
        org_id: str | None,
        key: str,
        statement: str,
        hits: list[dict[str, object]],
        copy: _Copy,
    ) -> FormatterTaskResult:
        target = await self._resolve_forget_target(user_id=user_id, key=key, statement=statement, hits=hits)
        if target is None:
            # Honest empty state: there is nothing to delete, and no card is minted
            # for a deletion that cannot happen (020 — no fake confirmation).
            return self._result(
                task_id=task_id,
                copy=copy,
                title=copy.forget_missing_title,
                body=copy.forget_missing_body.format(text=statement),
                status="success",
            )
        entry_key, stored_text = target
        try:
            card = await self._forget.request_forget(
                thread_id=thread_id,
                owner_user_id=user_id,
                org_id=org_id,
                namespace_kind=INTERACTIVE_NAMESPACE_KIND,
                scope_id=user_id,
                entry_key=entry_key,
            )
        except (ValueError, HitlInvalidActionError) as exc:
            logger.warning("memory_mutation.forget_unavailable", task_id=task_id, error=str(exc))
            return self._refusal_unavailable(task_id=task_id, copy=copy, reason=str(exc))
        await self._audit(task_id=task_id, thread_id=thread_id, kind="forget", card=card, entry_key=entry_key)
        return self._result(
            task_id=task_id,
            copy=copy,
            title=copy.forget_title,
            body=copy.forget_body.format(existing=stored_text[:200] or entry_key),
            card=card,
        )

    async def _resolve_forget_target(
        self,
        *,
        user_id: str,
        key: str,
        statement: str,
        hits: list[dict[str, object]],
    ) -> tuple[str, str] | None:
        """Exact key first (model hint), then the closest stored statement."""
        hint = MemoryMutationPolicy.coerce_key(key, text=statement)
        if hint and not hint.startswith(MEMORY_KEY_PREFIX):
            stored = await self._get_entry(user_id=user_id, entry_key=hint)
            if stored is not None:
                return hint, stored
        match = MemoryMutationPolicy.best_existing_match(hits, text=statement)
        if match is None:
            return None
        entry_key = str(match.get("_entry_key") or "").strip()
        if not entry_key:
            return None
        return entry_key, str(match.get("text") or "").strip()

    async def _get_entry(self, *, user_id: str, entry_key: str) -> str | None:
        try:
            entry = await self._memory.get(namespace=user_namespace(user_id), key=entry_key)
        except Exception:
            logger.exception("memory_mutation.entry_lookup_failed", entry_key=entry_key[:64])
            return None
        if entry is None:
            return None
        return str(entry.get("text") or "").strip()

    async def _read_check(self, *, user_id: str, statement: str) -> list[dict[str, object]]:
        """Read-only lookup; a failed read degrades to "nothing found", never to a write."""
        try:
            return await self._memory.search(
                namespace=user_namespace(user_id),
                query=statement,
                limit=_MUTATION_SEARCH_LIMIT,
            )
        except Exception:
            logger.exception("memory_mutation.read_check_failed", user_id=user_id)
            return []

    async def _audit(
        self,
        *,
        task_id: str,
        thread_id: str,
        kind: str,
        card: HITLCardView,
        entry_key: str,
    ) -> None:
        await write_audit(
            conversation_id=thread_id,
            event="memory_mutation_staged",
            metadata={
                "task_id": task_id,
                "kind": kind,
                "card_id": card.card_id,
                "entry_key": entry_key[:64],
            },
        )

    def _refusal_unavailable(self, *, task_id: str, copy: _Copy, reason: str) -> FormatterTaskResult:
        return self._result(
            task_id=task_id,
            copy=copy,
            title=copy.unavailable_title,
            body=copy.unavailable_body.format(reason=reason[:200]),
            status="failure",
            error="memory_mutation_unavailable",
        )

    def _result(
        self,
        *,
        task_id: str,
        copy: _Copy,
        title: str,
        body: str,
        card: HITLCardView | None = None,
        detail: str = "",
        status: Literal["success", "failure", "partial"] = "partial",
        error: str | None = None,
    ) -> FormatterTaskResult:
        """Answer document for a mutation turn (card is the only way the write happens)."""
        pending = card is not None
        confidence = _PENDING_CONFIDENCE if pending else _REFUSAL_CONFIDENCE
        detail_blocks = (ParagraphBlock(text=detail),) if detail else ()
        document = ContentDocument(
            locale=copy.locale,
            title=title,
            blocks=(
                HeadingBlock(level=2, text=title, icon="shield" if pending else "info"),
                ParagraphBlock(text=body),
                *detail_blocks,
            ),
            meta=DocumentMeta(
                confidence=confidence,
                requires_review=pending,
                source_refs=(),
                kind="response",
            ),
        )
        return FormatterTaskResult(
            task_id=task_id,
            agent_role="memory_mutation",
            status=status,
            confidence=confidence,
            requires_review=pending,
            output=document,
            hitl_cards=(card,) if card is not None else (),
            error=error,
        )
