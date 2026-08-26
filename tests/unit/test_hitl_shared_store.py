"""Shared Redis required for HITL in staging/production."""

from __future__ import annotations

import pytest

from palatium_ai.application.wiring import build_hitl_service

_HMAC = "unit-test-hitl-hmac-key-32bytes!!"  # noqa: S105


def test_require_shared_store_refuses_in_memory() -> None:
    with pytest.raises(RuntimeError, match="shared Redis"):
        build_hitl_service(
            redis_client=None,
            signing_secret=_HMAC,
            require_shared_store=True,
        )


def test_dev_allows_in_memory_without_redis() -> None:
    service = build_hitl_service(
        redis_client=None,
        signing_secret=_HMAC,
        require_shared_store=False,
        manager_roles=frozenset({"manager"}),
    )
    assert service is not None
