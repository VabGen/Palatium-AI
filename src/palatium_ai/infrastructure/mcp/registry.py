# src/palatium_ai/infrastructure/mcp/registry.py

"""MCPRegistry — регистрация MCP-серверов, tools cache и circuit breaker."""

from __future__ import annotations

import asyncio
import time

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog

from tenacity import retry, stop_after_attempt, wait_exponential

from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.server_url_policy import filter_mcp_server_map
from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient, MCPJsonRpcError
from palatium_ai.infrastructure.mcp.circuit import McpServerCircuit

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult

logger = structlog.get_logger(__name__)

_CONNECT_TIMEOUT_SECONDS = 2.0
_NEGATIVE_CACHE_TTL_SECONDS = 30.0


@dataclass(slots=True)
class _ToolsCacheEntry:
    tools: list[MCPToolDescriptor]
    cached_at: float
    ok: bool


class MCPRegistry:
    """Реестр MCP-серверов с TTL-кэшем descriptors и per-server circuit."""

    def __init__(
        self,
        settings: Settings,
        source_fetcher: Callable[[], Awaitable[dict[str, str]]] | None = None,
    ) -> None:
        self._settings = settings
        self._source_fetcher = source_fetcher
        self._servers: dict[str, str] = {}
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._tools_cache: dict[str, _ToolsCacheEntry] = {}
        self._circuits: dict[str, McpServerCircuit] = {}
        self._cache_ttl_seconds: int = 60
        self._lock = asyncio.Lock()
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    def _http_timeout(self) -> httpx.Timeout:
        read_timeout = float(self._settings.mcp.timeout_seconds)
        return httpx.Timeout(
            timeout=read_timeout,
            connect=_CONNECT_TIMEOUT_SECONDS,
        )

    async def initialize(self) -> None:
        """Первоначальная загрузка данных из источника."""
        if self._source_fetcher:
            raw = await self._source_fetcher()
        else:
            raw = self._settings.mcp.servers.copy()
        self._servers = self._accept_servers(raw)
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._http_timeout())
        self._assert_auth_coverage()
        self._initialized = True

    def _accept_servers(self, raw: dict[str, str]) -> dict[str, str]:
        accepted, rejected = filter_mcp_server_map(
            raw,
            allow_http_loopback=self._settings.mcp.allow_http_loopback,
            http_allowed_hosts=self._settings.mcp.http_host_allowlist(),
        )
        for name, reason in rejected:
            logger.warning("MCP server URL rejected", server=name or "(empty)", reason=reason)
        return accepted

    def _assert_auth_coverage(self) -> None:
        if not self._settings.mcp.auth_required:
            return
        missing = [name for name in self._servers if not self._settings.mcp.resolve_auth_token(name)]
        if missing:
            raise RuntimeError(
                "MCP_AUTH_REQUIRED=true but no token for servers: " + ", ".join(sorted(missing)),
            )

    def _auth_headers(self, server_name: str) -> dict[str, str]:
        token = self._settings.mcp.resolve_auth_token(server_name)
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def is_registered(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли сервер с указанным именем."""
        return name in self._servers

    def list_servers(self) -> list[str]:
        """Возвращает список имён зарегистрированных серверов."""
        return list(self._servers.keys())

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Возвращает HTTP-клиент для health-check (lazy init)."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._http_timeout())
        return self._http_client

    def _load_servers(self) -> dict[str, str]:
        """Загружает серверы из статической конфигурации."""
        return self._settings.mcp.servers.copy()

    def _clear_runtime_caches(self) -> None:
        self._health_cache.clear()
        self._tools_cache.clear()
        self._circuits.clear()

    async def reload(self) -> None:
        """Перезагружает данные из источника."""
        if self._source_fetcher:
            new_servers = self._accept_servers(await self._source_fetcher())
            if new_servers != self._servers:
                self._servers = new_servers
                self._clear_runtime_caches()
                self._assert_auth_coverage()
                logger.info("MCP registry reloaded", count=len(self._servers))

    def get_server_url(self, name: str) -> str | None:
        """Возвращает URL сервера по имени."""
        return self._servers.get(name)

    def get_client(self, name: str) -> MCPJsonRpcClient:
        """Возвращает JSON-RPC клиент для указанного MCP server."""
        server_url = self.get_server_url(name)
        if server_url is None:
            raise ValueError(f"Server '{name}' is not registered")
        return MCPJsonRpcClient(
            server_url=server_url,
            settings=self._settings,
            http_client=self.http_client,
            server_name=name,
        )

    async def is_available(self, name: str) -> bool:
        """Проверяет доступность сервера; результат кешируется на cache_ttl_seconds."""
        if not self.is_registered(name):
            raise ValueError(f"Server '{name}' is not registered")

        now = time.time()
        circuit = self._circuits.setdefault(name, McpServerCircuit())
        if circuit.is_open(now):
            return False

        if name in self._health_cache:
            cached_ok, cached_time = self._health_cache[name]
            if now - cached_time < self._cache_ttl_seconds:
                return cached_ok

        url = self._servers[name]
        try:
            async with self._lock:
                ok = await self._check_url(url, server_name=name)
        except Exception as e:
            logger.warning(
                "MCP health check failed",
                server=name,
                url=url,
                error=str(e),
                exc_info=True,
            )
            ok = False

        self._health_cache[name] = (ok, time.time())
        return ok

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )
    async def _check_url(self, url: str, *, server_name: str) -> bool:
        """Выполняет фактическую проверку URL (без follow redirects)."""
        try:
            response = await self.http_client.head(
                url,
                follow_redirects=False,
                headers=self._auth_headers(server_name),
            )
            if response.status_code in {401, 403, 404, 405}:
                # Some stubs reject HEAD; probe authenticated POST tools/list lightly via GET /health if present.
                health = await self.http_client.get(
                    url.rstrip("/") + "/health",
                    follow_redirects=False,
                    headers=self._auth_headers(server_name),
                )
                return health.is_success
            return response.is_success
        except httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError:
            return False

    def refresh(self) -> None:
        """Перезагружает список серверов из конфигурации и сбрасывает кеш."""
        self._servers = self._accept_servers(self._load_servers())
        self._clear_runtime_caches()
        self._assert_auth_coverage()
        logger.info("MCP registry refreshed", servers_count=len(self._servers))

    async def close(self) -> None:
        """Закрывает HTTP-клиент при завершении работы."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def available_servers(self) -> list[str]:
        """Возвращает список имён серверов, которые в данный момент доступны."""
        tasks = [self.is_available(name) for name in self._servers]
        results = await asyncio.gather(*tasks)
        return [name for name, ok in zip(self._servers, results, strict=False) if ok]

    def _circuit(self, server_name: str) -> McpServerCircuit:
        return self._circuits.setdefault(server_name, McpServerCircuit())

    async def list_tools(self, server_name: str, *, force_refresh: bool = False) -> list[MCPToolDescriptor]:
        """Получает tools/list; TTL-кэш + negative cache + circuit breaker."""
        now = time.time()
        circuit = self._circuit(server_name)
        if circuit.is_open(now):
            logger.debug("MCP circuit open; skipping tools/list", server=server_name)
            cached = self._tools_cache.get(server_name)
            return list(cached.tools) if cached is not None else []

        if not force_refresh:
            cached = self._tools_cache.get(server_name)
            if cached is not None:
                ttl = self._cache_ttl_seconds if cached.ok else _NEGATIVE_CACHE_TTL_SECONDS
                if now - cached.cached_at < ttl:
                    return list(cached.tools)

        client = self.get_client(server_name)
        server_url = self.get_server_url(server_name)
        try:
            tools = await client.list_tools()
        except httpx.HTTPError as exc:
            logger.warning(
                "MCP tools/list unavailable; skipping server",
                server=server_name,
                url=server_url,
                error=str(exc),
            )
            return self._remember_tools_failure(server_name, now)
        except MCPJsonRpcError as exc:
            logger.warning(
                "MCP tools/list returned JSON-RPC error; skipping server",
                server=server_name,
                url=server_url,
                error=str(exc),
            )
            return self._remember_tools_failure(server_name, now)
        except Exception as exc:
            logger.warning(
                "MCP tools/list failed; skipping server",
                server=server_name,
                url=server_url,
                error=str(exc),
                exc_info=True,
            )
            return self._remember_tools_failure(server_name, now)

        circuit.record_success()
        self._tools_cache[server_name] = _ToolsCacheEntry(tools=tools, cached_at=now, ok=True)
        return tools

    def _remember_tools_failure(self, server_name: str, now: float) -> list[MCPToolDescriptor]:
        self._circuit(server_name).record_failure(now)
        self._tools_cache[server_name] = _ToolsCacheEntry(tools=[], cached_at=now, ok=False)
        return []

    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        """Валидирует аргументы по JSON Schema 2020-12 и вызывает tools/call."""
        now = time.time()
        circuit = self._circuit(server_name)
        if circuit.is_open(now):
            logger.warning("MCP circuit open; refusing tools/call", server=server_name)
            raise MCPCircuitOpenError(server_name, retry_after_seconds=max(0.0, circuit.open_until - now))

        tools = await self.list_tools(server_name)
        descriptor = next((tool for tool in tools if tool.name == tool_call.name), None)
        if descriptor is None:
            raise ValueError(f"Tool '{tool_call.name}' is not declared by server '{server_name}'")

        MCPJsonRpcClient.validate_arguments(descriptor, tool_call.arguments)
        client = self.get_client(server_name)
        server_url = self.get_server_url(server_name)
        try:
            result = await client.call_tool(tool_call)
        except httpx.HTTPError as exc:
            circuit.record_failure(time.time())
            logger.warning(
                "MCP tools/call HTTP failure",
                server=server_name,
                url=server_url,
                tool=tool_call.name,
                error=str(exc),
            )
            raise
        except MCPJsonRpcError as exc:
            circuit.record_failure(time.time())
            logger.warning(
                "MCP tools/call JSON-RPC failure",
                server=server_name,
                url=server_url,
                tool=tool_call.name,
                error=str(exc),
            )
            raise
        except Exception:
            circuit.record_failure(time.time())
            raise

        circuit.record_success()
        return result

    @property
    def initialized(self) -> bool:
        """True, если реестр прошёл initialize()."""
        return self._initialized


class MCPCircuitOpenError(RuntimeError):
    """Raised when tools/call is blocked by an open per-server circuit."""

    def __init__(self, server_name: str, *, retry_after_seconds: float) -> None:
        self.server_name = server_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"MCP circuit open for '{server_name}' (retry after ~{retry_after_seconds:.0f}s)")
