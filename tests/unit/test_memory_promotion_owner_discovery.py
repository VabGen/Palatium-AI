"""Owner discovery for out-of-band memory promote (060, ADR 0002).

Under FORCE RLS a scheduler connection cannot enumerate tenants with a plain
``SELECT DISTINCT user_id``; ``--all-users`` resolves owners through the
SECURITY DEFINER RPC and merges them with any explicit scopes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from palatium_ai.jobs import memory_promote, memory_promotion_factory


class _MemorySettings:
    promote_enabled = True
    promote_min_importance = 0.7
    promote_batch_limit = 32


class _Settings:
    memory = _MemorySettings()


class _FakePromotionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def run_batch(self, *, user_id: str, limit: int) -> int:
        self.calls.append((user_id, limit))
        return 1


@pytest.mark.asyncio()
async def test_resolve_merges_explicit_and_discovered_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    discovered = AsyncMock(return_value=["u2", "u3"])
    monkeypatch.setattr(memory_promotion_factory, "list_promotion_owner_ids", discovered)

    resolved = await memory_promotion_factory.resolve_promotion_user_ids(
        session_factory=object(),  # type: ignore[arg-type]  # discovery is stubbed
        explicit=["u1", "u2", " "],
        all_users=True,
        min_importance=0.7,
    )

    assert resolved == ["u1", "u2", "u3"]
    discovered.assert_awaited_once()


@pytest.mark.asyncio()
async def test_resolve_without_all_users_keeps_explicit_order(monkeypatch: pytest.MonkeyPatch) -> None:
    discovered = AsyncMock()
    monkeypatch.setattr(memory_promotion_factory, "list_promotion_owner_ids", discovered)

    resolved = await memory_promotion_factory.resolve_promotion_user_ids(
        session_factory=object(),  # type: ignore[arg-type]
        explicit=["b", "a", "b"],
        all_users=False,
        min_importance=0.7,
    )

    assert resolved == ["b", "a"]
    discovered.assert_not_called()


@pytest.mark.asyncio()
async def test_memory_promote_all_users_runs_every_resolved_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakePromotionService()
    resolve = AsyncMock(return_value=["u1", "u2"])
    monkeypatch.setattr(memory_promote, "resolve_promotion_user_ids", resolve)
    monkeypatch.setattr(
        memory_promote,
        "build_memory_promotion_service",
        lambda **_kwargs: service,
    )

    exit_code = await memory_promote._run(
        settings=_Settings(),  # type: ignore[arg-type]
        session_factory=object(),  # type: ignore[arg-type]
        user_ids=[],
        all_users=True,
        limit=8,
    )

    assert exit_code == memory_promote.EXIT_SUCCESS
    assert service.calls == [("u1", 8), ("u2", 8)]
    resolve.assert_awaited_once()


@pytest.mark.asyncio()
async def test_memory_promote_requires_scope_without_all_users() -> None:
    exit_code = await memory_promote._run(
        settings=_Settings(),  # type: ignore[arg-type]
        session_factory=object(),  # type: ignore[arg-type]
        user_ids=[],
        all_users=False,
        limit=8,
    )

    assert exit_code == memory_promote.EXIT_INVALID_CONFIG


def test_memory_promote_parser_accepts_all_users() -> None:
    args: Any = memory_promote._build_parser().parse_args(["--all-users"])

    assert args.all_users is True
