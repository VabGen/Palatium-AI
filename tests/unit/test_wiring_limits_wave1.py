"""Wave 1 (P1): config values must actually reach the engine / client / LLM call.

Regression guard against "documented but ignored" settings (050: dead config).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from palatium_ai.core.config.database import DatabaseConfig, RedisConfig
from palatium_ai.core.config.llm.openai import OpenAILLMConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.infrastructure.cache.redis import create_redis_client
from palatium_ai.infrastructure.database.runtime import engine_pool_kwargs
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

_REDIS_FROM_URL = "palatium_ai.infrastructure.cache.redis.redis.from_url"
_LLM_ACOMPLETION = "palatium_ai.infrastructure.llm.litellm_adapter.acompletion"


def _db_config(**overrides: str) -> DatabaseConfig:
    env = {
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "POSTGRES_DB": "d",
        **overrides,
    }
    return DatabaseConfig.model_validate(env)


def test_engine_pool_kwargs_come_from_config() -> None:
    """DB_POOL_* must reach create_async_engine instead of being silently ignored."""
    db = _db_config(
        DB_POOL_SIZE="7",
        DB_MAX_OVERFLOW="3",
        DB_POOL_PRE_PING="false",
        DB_POOL_TIMEOUT_SECONDS="12",
    )
    assert engine_pool_kwargs(db) == {
        "pool_size": 7,
        "max_overflow": 3,
        "pool_pre_ping": False,
        "pool_timeout": 12.0,
    }


def test_database_config_rejects_invalid_pool_size() -> None:
    with pytest.raises(ValueError):
        _db_config(DB_POOL_SIZE="0")


@pytest.mark.asyncio()
async def test_redis_client_applies_pool_and_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_from_url(dsn: str, **kwargs: object) -> object:
        captured["dsn"] = dsn
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(_REDIS_FROM_URL, _fake_from_url)
    settings = SimpleNamespace(
        redis=RedisConfig.model_validate(
            {
                "REDIS_MAX_CONNECTIONS": "9",
                "REDIS_SOCKET_TIMEOUT_SECONDS": "3",
                "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS": "4",
                "REDIS_HEALTH_CHECK_INTERVAL_SECONDS": "11",
                "REDIS_SOCKET_KEEPALIVE": "false",
            }
        )
    )
    await create_redis_client(settings)  # type: ignore[arg-type]

    assert captured["max_connections"] == 9
    assert captured["socket_timeout"] == 3.0
    assert captured["socket_connect_timeout"] == 4.0
    assert captured["health_check_interval"] == 11
    assert captured["socket_keepalive"] is False


@pytest.mark.asyncio()
async def test_llm_generate_forwards_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENAI_TIMEOUT must reach acompletion; previously the field was dead config."""
    captured: dict[str, object] = {}

    async def _fake_acompletion(**params: object) -> object:
        captured.update(params)
        return SimpleNamespace(choices=[], model="gpt-4o", usage=None)

    monkeypatch.setattr(_LLM_ACOMPLETION, _fake_acompletion)
    config = OpenAILLMConfig.model_validate({"OPENAI_API_KEY": "k", "OPENAI_TIMEOUT": "42"})

    await LiteLLMAdapter(config).generate([ChatMessage(role="user", content="hi")])

    assert captured["timeout"] == 42.0


def test_llm_timeout_accessor_ignores_non_positive() -> None:
    """A zero/negative timeout means "provider default", not "no timeout field"."""
    config = OpenAILLMConfig.model_validate({"OPENAI_API_KEY": "k", "OPENAI_TIMEOUT": "0"})
    assert config.get_timeout_seconds() is None


def test_database_startup_and_connect_timeouts_are_configurable() -> None:
    db = _db_config(DB_STARTUP_TIMEOUT_SECONDS="5", DB_CONNECT_TIMEOUT_SECONDS="3")
    assert db.startup_timeout_seconds == 5.0
    assert db.connect_timeout_seconds == 3.0
