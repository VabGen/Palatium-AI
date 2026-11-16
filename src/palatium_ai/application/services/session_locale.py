# src/palatium_ai/application/services/session_locale.py

"""Resolve sticky reply locale from a session record (HITL / off-graph chrome)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.session_service import SessionService


async def resolve_thread_response_locale(
    session_service: SessionService | None,
    *,
    thread_id: str,
    fallback_text: str = "",
) -> str:
    """BCP-47 from session ``response_locale`` / ``ui_locale``, else script of ``fallback_text``."""
    prior: str | None = None
    ui: str | None = None
    user_text = fallback_text
    if session_service is not None and thread_id.strip():
        session = await session_service.get_session(thread_id=thread_id.strip())
        if session is not None and isinstance(session.context, dict):
            prior_raw = session.context.get("response_locale")
            ui_raw = session.context.get("ui_locale")
            text_raw = session.context.get("last_user_text")
            prior = prior_raw if isinstance(prior_raw, str) else None
            ui = ui_raw if isinstance(ui_raw, str) else None
            if isinstance(text_raw, str) and text_raw.strip():
                user_text = text_raw
    return ReplyLocalePolicy.resolve(
        user_text=user_text,
        prior_locale=prior,
        ui_locale=ui,
    )


__all__ = ["resolve_thread_response_locale"]
