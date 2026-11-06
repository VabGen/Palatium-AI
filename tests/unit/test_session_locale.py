"""Sticky HITL/off-graph locale comes from session, not from technical previews."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.session_locale import resolve_thread_response_locale


@pytest.mark.asyncio
async def test_session_response_locale_beats_argument_preview_script() -> None:
    session = SimpleNamespace(
        context={"response_locale": "ru-RU", "ui_locale": "en-US", "last_user_text": "hello"},
    )
    service = SimpleNamespace(get_session=AsyncMock(return_value=session))

    locale = await resolve_thread_response_locale(
        service,  # type: ignore[arg-type]
        thread_id="th-1",
        fallback_text="ns=user/abc; key=pref",
    )

    assert locale == "ru-RU"


@pytest.mark.asyncio
async def test_missing_session_falls_back_to_preview_script() -> None:
    service = SimpleNamespace(get_session=AsyncMock(return_value=None))

    locale = await resolve_thread_response_locale(
        service,  # type: ignore[arg-type]
        thread_id="th-1",
        fallback_text="Сохранить предпочтение о языке",
    )

    assert locale.startswith("ru")
