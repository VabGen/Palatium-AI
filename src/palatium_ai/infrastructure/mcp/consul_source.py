# src/palatium_ai/infrastructure/mcp/consul_source.py

"""Модуль ConsulMCPSource содержит класс ConsulMCPSource.

Класс ConsulMCPSource используется для получения списка MCP-серверов из Consul KV.
"""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Any

import consul
import structlog

from tenacity import retry, stop_after_attempt, wait_exponential

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from palatium_ai.core.config.mcp import MCPConfig

logger = structlog.get_logger(__name__)


class ConsulMCPSource:
    """
    Получает словарь {имя_сервера: URL} из Consul KV.

    Использует блокирующие запросы (watch) для мгновенного обновления.
    """

    def __init__(self, config: MCPConfig) -> None:
        self._config = config
        if config.consul_url is None:
            raise ValueError("MCPConfig.consul_url must be set to use ConsulMCPSource")
        self._client = consul.Consul(
            host=config.consul_url.replace("http://", "").replace("https://", ""),
            token=(config.consul_token.get_secret_value() if config.consul_token is not None else None),
            dc=config.consul_datacenter,
        )
        self._last_index: int | None = None
        self._cache: dict[str, str] = {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5))
    async def fetch(self) -> dict[str, str]:
        """Возвращает актуальный словарь серверов.

        Использует блокирующий запрос, если есть индекс.
        """
        loop = asyncio.get_event_loop()

        def _sync_fetch() -> tuple[int | None, list[dict[str, Any]] | None]:
            index, data = self._client.kv.get(
                self._config.consul_prefix,
                recurse=True,
                index=self._last_index,
                wait="60s",
            )
            return index, data

        index, data = await loop.run_in_executor(None, _sync_fetch)

        if index == self._last_index:
            return self._cache

        self._last_index = index
        if not data:
            self._cache = {}
        else:
            servers = {}
            for item in data:
                key = item["Key"]
                if key.startswith(self._config.consul_prefix):
                    name = key[len(self._config.consul_prefix) :]
                    servers[name] = item["Value"].decode("utf-8")
            self._cache = servers
        return self._cache

    async def watch(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Фоновый цикл: опрашивает Consul и вызывает callback при изменении данных."""
        while True:
            try:
                previous = self._cache.copy()
                await self.fetch()
                if self._cache != previous:
                    await callback()
            except Exception as e:
                logger.warning("Consul watch failed", error=str(e), exc_info=True)
                await asyncio.sleep(self._config.consul_watch_interval)
