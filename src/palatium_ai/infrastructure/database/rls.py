# src/palatium_ai/infrastructure/database/rls.py

"""Postgres Row-Level Security session binding (060)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_RLS_SETTING = "palatium.user_id"


async def set_rls_user_scope(session: AsyncSession, user_id: str) -> None:
    """Bind ``palatium.user_id`` for the current transaction (fail-closed).

    RLS policies on ``memory.entries`` / ``knowledge.*`` compare ``user_id`` to
    this setting. Empty scope must never open a cross-tenant window.
    """
    uid = user_id.strip()
    if not uid:
        msg = "RLS user scope requires non-empty user_id"
        raise ValueError(msg)
    await session.execute(
        text("SELECT set_config(:key, :uid, true)"),
        {"key": _RLS_SETTING, "uid": uid},
    )
