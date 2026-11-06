# src/palatium_ai/domain/hitl/copy.py

"""Locale-aware HITL card copy — one place for quality / MCP labels (020, 055).

Card chrome is server-owned: never leave English labels on a Russian turn (or the
reverse). Locale comes from the answer document / reply axis, not from the browser.
"""

from __future__ import annotations

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


_RU_PREFIXES: Final[tuple[str, ...]] = ("ru", "be", "uk", "kk")


def _is_cyrillic_locale(locale: str | None) -> bool:
    raw = (locale or "").strip().lower().replace("_", "-")
    if not raw:
        return False
    primary = raw.split("-", 1)[0]
    return primary in _RU_PREFIXES


class HitlCopyPolicy:
    """Pure copy factory keyed by reply locale."""

    @classmethod
    def review(
        cls,
        *,
        locale: str | None,
        confidence: float,
        document_title: str | None = None,
    ) -> HitlReviewCopy:
        title = (document_title or "").strip()
        if _is_cyrillic_locale(locale):
            return HitlReviewCopy(
                title=title or "Требуется проверка",
                body=(
                    f"Контроль качества отметил этот ответ (уверенность {confidence:.2f}). "
                    "Подтвердите, чтобы оставить его, или отклоните для переработки — "
                    "не отвечайте нумерованным меню."
                ),
                options=_review_options_ru(),
            )
        return HitlReviewCopy(
            title=title or "Review required",
            body=(
                f"Quality gate flagged this answer (confidence {confidence:.2f}). "
                "Approve to keep it, or Reject & revise to regenerate — do not reply "
                "with a numbered menu."
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
    ) -> HitlToolApprovalCopy:
        preview = argument_preview.strip()[:500] or "(no arguments)"
        if _is_cyrillic_locale(locale):
            return HitlToolApprovalCopy(
                title=f"Разрешить инструмент: {server_name}.{tool_name}",
                body=(f"Побочный эффект={side_effect}. Инструмент не выполнится, пока вы не подтвердите. Аргументы: {preview}"),
                options=_tool_options_ru(),
            )
        return HitlToolApprovalCopy(
            title=f"Approve MCP tool: {server_name}.{tool_name}",
            body=(f"Side effect={side_effect}. Tool will not run until you approve. Arguments: {preview}"),
            options=_tool_options_en(),
        )

    @classmethod
    def tool_paused(
        cls,
        *,
        locale: str | None,
        server_name: str,
        tool_name: str,
        side_effect: str,
    ) -> HitlToolPausedCopy:
        if _is_cyrillic_locale(locale):
            return HitlToolPausedCopy(
                title="Требуется подтверждение инструмента",
                heading="Нужно подтверждение перед вызовом",
                body=(
                    f"Ожидание решения по MCP `{server_name}.{tool_name}` "
                    f"(побочный эффект={side_effect}). Выберите «Разрешить» или «Запретить»."
                ),
            )
        return HitlToolPausedCopy(
            title="Tool approval required",
            heading="Human approval required before tool call",
            body=(f"Paused before MCP `{server_name}.{tool_name}` (side_effect={side_effect}). Choose Allow or Deny."),
        )


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


def _tool_options_ru() -> tuple[HITLOption, ...]:
    return (
        HITLOption(
            action_id="approve",
            label="Разрешить вызов",
            kind="approve",
            style="primary",
            icon="shield",
        ),
        HITLOption(
            action_id="reject",
            label="Запретить вызов",
            kind="reject",
            style="danger",
            icon="x",
        ),
    )


def _tool_options_en() -> tuple[HITLOption, ...]:
    return (
        HITLOption(
            action_id="approve",
            label="Allow tool call",
            kind="approve",
            style="primary",
            icon="shield",
        ),
        HITLOption(
            action_id="reject",
            label="Deny tool call",
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
