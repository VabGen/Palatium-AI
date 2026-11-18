"""Re-probe thread_file_named after Contextualizer / choice resume (055)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from palatium_ai.application.orchestration.nodes import (
    _prior_user_ask_for_file_inherit,
    _resolve_thread_file_named_for_continuity,
)
from palatium_ai.application.services.turn_attachment_context import (
    TurnAttachmentContext,
    turn_attachment_context,
)
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


def _window(*texts: tuple[str, str]) -> DialogTurnWindow:
    turns = tuple(
        DialogTurn(
            id=uuid4(),
            thread_id="t1",
            role=role,  # type: ignore[arg-type]
            content=content,
            seq=i,
            created_at=datetime.now(UTC),
        )
        for i, (role, content) in enumerate(texts)
    )
    return DialogTurnWindow(thread_id="t1", turns=turns, limit=12)


def test_prior_user_ask_skips_hitl_envelope() -> None:
    window = _window(
        ("user", "файл договор"),
        ("assistant", "Выберите формат…"),
        ("user", "<<<HITL_CHOICE_RESUME kind=format action_id=thesis option_kind=format>>>Тезисный анализ"),
    )
    assert _prior_user_ask_for_file_inherit(window) == "файл договор"


@pytest.mark.asyncio()
async def test_choice_slot_reprobe_promotes_named_file_from_rewrite() -> None:
    """HITL envelope is not a filename; rewritten prior ask must promote storage axis."""
    window = _window(
        ("user", "файл договор"),
        ("assistant", "Выберите формат анализа…"),
    )
    names = AsyncMock(return_value=True)
    with turn_attachment_context(TurnAttachmentContext(names_thread_file=names)):
        named = await _resolve_thread_file_named_for_continuity(
            entry_named=False,
            rewritten="файл договор\n[selected_option action_id=thesis] Тезисный анализ",
            choice_slot_filled=True,
            raw_ask="<<<HITL_CHOICE_RESUME kind=format action_id=thesis option_kind=format>>>",
            window=window,
        )
    assert named is True
    names.assert_awaited()


@pytest.mark.asyncio()
async def test_entry_named_skips_reprobe_unless_choice_slot() -> None:
    names = AsyncMock(return_value=False)
    with turn_attachment_context(TurnAttachmentContext(names_thread_file=names)):
        named = await _resolve_thread_file_named_for_continuity(
            entry_named=True,
            rewritten="irrelevant",
            choice_slot_filled=False,
            raw_ask="тезисный анализ файла договор",
            window=_window(("user", "тезисный анализ файла договор")),
        )
    assert named is True
    names.assert_not_awaited()
