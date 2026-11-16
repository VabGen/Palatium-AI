# src/palatium_ai/domain/hitl/copy.py

"""Locale-aware HITL card copy — one place for quality / MCP labels (020, 055).

Card chrome is server-owned: never leave English labels on a Russian turn (or the
reverse). Locale comes from the answer document / reply axis, not from the browser.

Tool-approval copy follows Big Tech 2026 / Cloudscape «User authorized actions»:
consequence-first title + short human body. Raw MCP ids, side_effect=, risk floats,
namespace/user UUIDs and argument dumps stay out of the default body (audit owns them).
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Final

from palatium_ai.domain.hitl.cards import HITLOption


@dataclass(frozen=True, slots=True)
class HitlReviewCopy:
    """Title, body and options for a quality-gate review card."""

    title: str
    body: str
    options: tuple[HITLOption, ...]


@dataclass(frozen=True, slots=True)
class HitlToolApprovalCopy:
    """Title, body and options for an MCP tool approval card."""

    title: str
    body: str
    options: tuple[HITLOption, ...]


@dataclass(frozen=True, slots=True)
class HitlToolPausedCopy:
    """Framing document shown in chat while MCP tool approval is pending."""

    title: str
    heading: str
    body: str


@dataclass(frozen=True, slots=True)
class _ToolIntent:
    """Human intent for a known platform/MCP tool (not the wire name)."""

    title_ru: str
    title_en: str
    body_ru: str
    body_en: str
    #: Optional preview field whose value is the user-facing payload (e.g. memory text).
    quote_field: str | None = None
    approve_ru: str = "Разрешить"
    approve_en: str = "Allow"
    deny_ru: str = "Запретить"
    deny_en: str = "Deny"


_RU_PREFIXES: Final[tuple[str, ...]] = ("ru", "be", "uk", "kk")
#: Cyrillic block — used when locale is ``und``/empty but the answer prose is already RU.
_CYRILLIC_RANGE: Final[tuple[int, int]] = (0x0400, 0x04FF)

#: Closed catalogue of product tools → consequence copy (055: not phrase lists in agents).
_TOOL_INTENTS: Final[dict[tuple[str, str], _ToolIntent]] = {
    ("platform", "save_memory"): _ToolIntent(
        title_ru="Сохранить в память?",
        title_en="Save to memory?",
        body_ru="Запомню это и смогу использовать в следующих ответах.",
        body_en="I'll remember this and may use it in later replies.",
        quote_field="text",
        approve_ru="Сохранить",
        approve_en="Save",
        deny_ru="Не сохранять",
        deny_en="Don't save",
    ),
    ("platform", "forget_memory"): _ToolIntent(
        title_ru="Удалить из памяти?",
        title_en="Forget this memory?",
        body_ru="Запись будет удалена из вашей памяти.",
        body_en="This memory entry will be removed.",
        approve_ru="Удалить",
        approve_en="Forget",
        deny_ru="Оставить",
        deny_en="Keep",
    ),
    ("platform", "extract_transcript_memories"): _ToolIntent(
        title_ru="Извлечь факты из диалога?",
        title_en="Extract facts from this chat?",
        body_ru="Из диалога будут сохранены важные факты в память.",
        body_en="Important facts from this chat will be saved to memory.",
    ),
    ("platform", "clear_memory"): _ToolIntent(
        title_ru="Очистить всю память?",
        title_en="Clear all memory?",
        body_ru="Будут удалены сохранённые факты и предпочтения. Это нельзя отменить.",
        body_en="Saved facts and preferences will be deleted. This cannot be undone.",
        approve_ru="Очистить",
        approve_en="Clear all",
        deny_ru="Отмена",
        deny_en="Cancel",
    ),
    ("platform", "ingest_document"): _ToolIntent(
        title_ru="Добавить документ в базу знаний?",
        title_en="Add this document to knowledge?",
        body_ru="Документ будет проиндексирован и станет доступен для поиска.",
        body_en="The document will be indexed and available for search.",
    ),
    ("platform", "skill_manage"): _ToolIntent(
        title_ru="Изменить навык?",
        title_en="Change this skill?",
        body_ru="Настройки навыка будут обновлены.",
        body_en="Skill settings will be updated.",
    ),
    ("platform", "memory_verify"): _ToolIntent(
        title_ru="Подтвердить запись в памяти?",
        title_en="Verify this memory?",
        body_ru="Статус доверия к записи в памяти будет обновлён.",
        body_en="The trust status of this memory entry will be updated.",
    ),
}

_PREVIEW_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[;,\s])(?P<key>[A-Za-z_][\w]*)=(?P<value>.+?)(?=(?:[;,]?\s*[A-Za-z_][\w]*=)|$)",
    re.DOTALL,
)


def _is_cyrillic_locale(locale: str | None) -> bool:
    raw = (locale or "").strip().lower().replace("_", "-")
    if not raw:
        return False
    primary = raw.split("-", 1)[0]
    return primary in _RU_PREFIXES


def _prose_looks_cyrillic(*hints: str | None) -> bool:
    """True when any hint carries Cyrillic letters (und locale still needs RU chrome)."""
    for hint in hints:
        text = (hint or "").strip()
        if not text:
            continue
        for char in text:
            code = ord(char)
            if _CYRILLIC_RANGE[0] <= code <= _CYRILLIC_RANGE[1]:
                return True
    return False


def _use_cyrillic_copy(locale: str | None, *prose_hints: str | None) -> bool:
    """Locale wins; ``und``/empty falls back to prose script so RU answers never get EN HITL."""
    if _is_cyrillic_locale(locale):
        return True
    raw = (locale or "").strip().lower().replace("_", "-")
    primary = raw.split("-", 1)[0] if raw else ""
    # Explicit Latin locales must stay English even if a proper noun has Cyrillic.
    if primary and primary not in ("und", "zxx") and primary not in _RU_PREFIXES:
        return False
    return _prose_looks_cyrillic(*prose_hints)


def _preview_fields(preview: str) -> dict[str, str]:
    """Parse ``key=value`` pairs from HITL argument previews (ns=/text=/…)."""
    raw = preview.strip()
    if not raw:
        return {}
    found: dict[str, str] = {}
    for match in _PREVIEW_FIELD_RE.finditer(raw):
        key = match.group("key").strip().lower()
        value = match.group("value").strip().rstrip(";,").strip()
        if key and value:
            found[key] = value
    return found


def _quote_snippet(value: str, *, max_len: int = 160) -> str:
    text = " ".join(value.split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1]}…"


def _body_with_quote(base: str, preview: str, quote_field: str | None, *, cyrillic: bool) -> str:
    if not quote_field:
        return base
    fields = _preview_fields(preview)
    quoted = fields.get(quote_field.lower(), "").strip()
    if not quoted or quoted in {"{}", "(no arguments)"}:
        return base
    snippet = _quote_snippet(quoted)
    if cyrillic:
        return f"{base}\n\n«{snippet}»"
    return f'{base}\n\n"{snippet}"'


def _generic_tool_copy(*, cyrillic: bool, side_effect: str) -> tuple[str, str]:
    effect = side_effect.strip().lower()
    if cyrillic:
        title = "Разрешить это действие?"
        if effect == "write":
            body = "Ассистент хочет изменить данные. Продолжить только если вы согласны."
        elif effect == "read":
            body = "Ассистент хочет прочитать данные. Продолжить только если вы согласны."
        else:
            body = "Ассистент просит подтверждение, прежде чем продолжить."
        return title, body
    title = "Allow this action?"
    if effect == "write":
        body = "The assistant wants to change data. Continue only if you agree."
    elif effect == "read":
        body = "The assistant wants to read data. Continue only if you agree."
    else:
        body = "The assistant needs your confirmation before continuing."
    return title, body


class HitlCopyPolicy:
    """Pure copy factory keyed by reply locale (+ prose fallback when locale is und)."""

    @classmethod
    def review(
        cls,
        *,
        locale: str | None,
        confidence: float,
        document_title: str | None = None,
        prose_hint: str | None = None,
    ) -> HitlReviewCopy:
        # confidence stays in the signature for callers / metrics; body is
        # consequence-first (no ops floats — Cloudscape / ChatGPT pattern).
        _ = confidence
        title = (document_title or "").strip()
        if _use_cyrillic_copy(locale, title, prose_hint):
            return HitlReviewCopy(
                title=title or "Требуется проверка",
                body=(
                    "Контроль качества отметил этот ответ. "
                    "Подтвердите, чтобы оставить его, или отклоните для переработки."
                ),
                options=_review_options_ru(),
            )
        return HitlReviewCopy(
            title=title or "Review required",
            body=(
                "Quality gate flagged this answer. "
                "Approve to keep it, or reject to regenerate."
            ),
            options=_review_options_en(),
        )

    @classmethod
    def tool_approval(
        cls,
        *,
        locale: str | None,
        server_name: str,
        tool_name: str,
        side_effect: str,
        argument_preview: str,
        prose_hint: str | None = None,
    ) -> HitlToolApprovalCopy:
        """Consequence-first tool card; never dump MCP wire names or raw args by default."""
        preview = argument_preview.strip()[:500]
        cyrillic = _use_cyrillic_copy(locale, prose_hint, argument_preview)
        intent = _TOOL_INTENTS.get((server_name.strip().lower(), tool_name.strip().lower()))
        if intent is not None:
            title = intent.title_ru if cyrillic else intent.title_en
            base = intent.body_ru if cyrillic else intent.body_en
            body = _body_with_quote(base, preview, intent.quote_field, cyrillic=cyrillic)
            return HitlToolApprovalCopy(
                title=title,
                body=body,
                options=_tool_options(
                    cyrillic=cyrillic,
                    approve=intent.approve_ru if cyrillic else intent.approve_en,
                    deny=intent.deny_ru if cyrillic else intent.deny_en,
                ),
            )
        title, body = _generic_tool_copy(cyrillic=cyrillic, side_effect=side_effect)
        return HitlToolApprovalCopy(
            title=title,
            body=body,
            options=_tool_options(
                cyrillic=cyrillic,
                approve="Разрешить" if cyrillic else "Allow",
                deny="Запретить" if cyrillic else "Deny",
            ),
        )

    @classmethod
    def tool_paused(
        cls,
        *,
        locale: str | None,
        server_name: str,
        tool_name: str,
        side_effect: str,
        prose_hint: str | None = None,
    ) -> HitlToolPausedCopy:
        cyrillic = _use_cyrillic_copy(locale, prose_hint)
        intent = _TOOL_INTENTS.get((server_name.strip().lower(), tool_name.strip().lower()))
        if intent is not None:
            title = intent.title_ru if cyrillic else intent.title_en
            body = intent.body_ru if cyrillic else intent.body_en
            if cyrillic:
                return HitlToolPausedCopy(
                    title="Нужно подтверждение",
                    heading=title,
                    body=f"{body} Выберите действие на карточке ниже.",
                )
            return HitlToolPausedCopy(
                title="Confirmation needed",
                heading=title,
                body=f"{body} Choose an action on the card below.",
            )
        title, body = _generic_tool_copy(cyrillic=cyrillic, side_effect=side_effect)
        if cyrillic:
            return HitlToolPausedCopy(
                title="Нужно подтверждение",
                heading=title,
                body=f"{body} Выберите действие на карточке ниже.",
            )
        return HitlToolPausedCopy(
            title="Confirmation needed",
            heading=title,
            body=f"{body} Choose an action on the card below.",
        )

    @classmethod
    def choice_fallback_title(
        cls,
        *,
        locale: str | None,
        prose_hint: str | None = None,
    ) -> str:
        """Default user_choice title when the document has no title of its own."""
        if _use_cyrillic_copy(locale, prose_hint):
            return "Выберите один вариант"
        return "Choose an option"


def _review_options_ru() -> tuple[HITLOption, ...]:
    return (
        HITLOption(
            action_id="approve",
            label="Подтвердить",
            kind="approve",
            style="primary",
            icon="check",
        ),
        HITLOption(
            action_id="reject",
            label="Отклонить и переработать",
            kind="reject",
            style="danger",
            icon="x",
        ),
    )


def _review_options_en() -> tuple[HITLOption, ...]:
    return (
        HITLOption(
            action_id="approve",
            label="Approve",
            kind="approve",
            style="primary",
            icon="check",
        ),
        HITLOption(
            action_id="reject",
            label="Reject & revise",
            kind="reject",
            style="danger",
            icon="x",
        ),
    )


def _tool_options(*, cyrillic: bool, approve: str, deny: str) -> tuple[HITLOption, ...]:
    _ = cyrillic
    return (
        HITLOption(
            action_id="approve",
            label=approve,
            kind="approve",
            style="primary",
            icon="shield",
        ),
        HITLOption(
            action_id="reject",
            label=deny,
            kind="reject",
            style="danger",
            icon="x",
        ),
    )


__all__ = [
    "HitlCopyPolicy",
    "HitlReviewCopy",
    "HitlToolApprovalCopy",
    "HitlToolPausedCopy",
]
