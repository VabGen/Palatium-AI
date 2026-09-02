# src/palatium_ai/application/bootstrap.py

"""Инициализация и завершение ресурсов приложения."""

from __future__ import annotations

import asyncio
import contextlib
import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.application.services.session_service import SessionService
from palatium_ai.application.wiring import build_hitl_service, build_intent_service, warm_mcp_capability_cache
from palatium_ai.core.logging import logger, setup_logging
from palatium_ai.core.observability.langsmith_env import apply_langsmith_env
from palatium_ai.infrastructure.cache.redis import create_redis_client, ensure_redis_connection
from palatium_ai.infrastructure.database.init_db import (
    ensure_database_and_schema,
)
from palatium_ai.infrastructure.database.repositories import (
    McpToolCallRepository,
    SessionRepository,
)
from palatium_ai.infrastructure.database.runtime import create_session_factory
from palatium_ai.infrastructure.embeddings.factory import create_embedding_client
from palatium_ai.infrastructure.mcp.consul_source import ConsulMCPSource
from palatium_ai.infrastructure.mcp.registry import MCPRegistry
from palatium_ai.infrastructure.memory.checkpointer import (
    CheckpointerHandle,
    create_checkpointer,
    ensure_psycopg_compatible_loop,
)
from palatium_ai.infrastructure.memory.dialog_turn_store import PostgresDialogTurnStore
from palatium_ai.infrastructure.memory.embedding_rerank import EmbeddingRerankMemoryPort
from palatium_ai.infrastructure.memory.graphiti_adapter import GraphitiMemoryPort, GraphitiSdkTransport
from palatium_ai.infrastructure.memory.mem0_adapter import Mem0HttpTransport, Mem0MemoryPort
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

    from palatium_ai.application.services.intent_service import IntentService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

_HITL_SWEEP_INTERVAL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class AppResources:
    """Ресурсы, инициализируемые при старте приложения."""

    settings: Settings
    mcp_registry: MCPRegistry
    intent_service: IntentService
    session_service: SessionService
    hitl_service: HitlService
    kill_switch: KillSwitchService
    db_engine: AsyncEngine
    mcp_tool_call_repository: McpToolCallRepository
    redis_client: Redis
    dialog_turn_store: DialogTurnStore | None = None
    memory_port: MemoryPort | None = None
    consolidation: MemoryConsolidationService | None = None
    checkpointer_handle: CheckpointerHandle | None = None
    background_tasks: tuple[asyncio.Task[None], ...] = field(default_factory=tuple)


async def load_mcp_servers_from_json_file(file_path: str) -> dict[str, str]:
    """Асинхронно загружает словарь серверов из JSON-файла."""
    path = Path(file_path)
    if not path.exists():
        logger.warning("MCP servers file not found", path=str(path))
        return {}
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            logger.warning("MCP servers file must contain a dict", path=str(path))
            return {}
        return {str(key): str(value) for key, value in data.items()}
    except Exception as exc:
        logger.error("Failed to load MCP servers from file", path=str(path), error=str(exc))
        return {}


def _build_memory_port(settings: Settings, session_factory: object) -> MemoryPort:
    """Select MemoryPort backend (postgres | mem0 | graphiti) + optional rerank."""
    backend = settings.memory.backend
    if backend == "mem0":
        mem0_key = settings.memory.mem0_api_key.get_secret_value() if settings.memory.mem0_api_key is not None else ""
        port: MemoryPort = Mem0MemoryPort(
            Mem0HttpTransport(
                api_key=mem0_key,
                host=settings.memory.mem0_host,
                timeout_seconds=settings.memory.mem0_timeout_seconds,
            )
        )
        logger.info("MemoryPort: Mem0 Platform", host=settings.memory.mem0_host)
    elif backend == "graphiti":
        neo4j_password = (
            settings.memory.graphiti_neo4j_password.get_secret_value()
            if settings.memory.graphiti_neo4j_password is not None
            else ""
        )
        port = GraphitiMemoryPort(
            GraphitiSdkTransport(
                uri=settings.memory.graphiti_neo4j_uri,
                user=settings.memory.graphiti_neo4j_user,
                password=neo4j_password,
            )
        )
        logger.info("MemoryPort: Graphiti", uri=settings.memory.graphiti_neo4j_uri)
    else:
        port = PostgresMemoryPort(session_factory)  # type: ignore[arg-type]
        logger.info("MemoryPort: Postgres memory_items")

    if settings.memory.embedding_rerank and backend == "postgres":
        try:
            port = EmbeddingRerankMemoryPort(port, create_embedding_client(settings))
            logger.info("MemoryPort: Postgres + embedding rerank")
        except Exception as exc:
            logger.warning("Memory embedding rerank disabled", error=str(exc))
    elif settings.memory.embedding_rerank:
        logger.info("MEMORY_EMBEDDING_RERANK ignored for non-postgres backend", backend=backend)
    return port


async def startup(settings: Settings) -> AppResources:
    """Инициализирует логирование, БД, Redis и MCP-реестр."""
    ensure_psycopg_compatible_loop()
    setup_logging(settings)
    apply_langsmith_env(settings.observability)
    # `environment` уже добавляется в контекстvars в `setup_logging`, поэтому не дублируем поле `env`.
    logger.info(f"{settings.app.name} starting...")

    await ensure_database_and_schema(settings)
    await ensure_redis_connection(settings)
    redis_client = await create_redis_client(settings)
    await redis_client.ping()
    logger.info("Database and Redis connections established")

    source: ConsulMCPSource | None = None
    fetcher: Callable[[], Awaitable[dict[str, str]]] | None = None

    if settings.mcp.consul_url:
        source = ConsulMCPSource(settings.mcp)
        fetcher = source.fetch
        logger.info("MCP source: Consul", url=settings.mcp.consul_url)
    elif settings.mcp.servers_file:

        async def fetcher_from_file() -> dict[str, str]:
            return await load_mcp_servers_from_json_file(settings.mcp.servers_file or "")

        fetcher = fetcher_from_file
        logger.info("MCP source: file", path=settings.mcp.servers_file)
    else:
        logger.info("MCP source: static (env)")

    mcp_registry = MCPRegistry(settings=settings, source_fetcher=fetcher)
    await mcp_registry.initialize()
    logger.info("MCP registry initialized", servers_count=len(mcp_registry.list_servers()))

    background_tasks: list[asyncio.Task[None]] = []
    if source is not None:
        background_tasks.append(asyncio.create_task(source.watch(mcp_registry.reload)))
        logger.info("MCP watch started")

    db_engine, session_factory = create_session_factory(settings)
    session_repository = SessionRepository(session_factory)
    mcp_tool_call_repository = McpToolCallRepository(session_factory)
    session_service = SessionService(session_repository)
    hitl_signing = settings.security.optional_hitl_hmac_secret()
    if hitl_signing is None:
        # Dev without JWT: still bind HITL actions; never empty.
        hitl_signing = f"dev-hitl-{settings.app.name}-local-only"
        logger.warning("HITL signing secret falling back to derived local key")
    hitl_service = build_hitl_service(
        redis_client=redis_client,
        signing_secret=hitl_signing,
        manager_roles=settings.security.manager_role_set,
        require_shared_store=settings.app.environment in {"staging", "production"},
        step_up_required=settings.security.effective_hitl_step_up_required(settings.app.environment),
        security=settings.security,
    )
    kill_switch = KillSwitchService(redis_client=redis_client)
    dialog_turn_store = PostgresDialogTurnStore(session_factory)
    memory_port = _build_memory_port(settings, session_factory)
    checkpointer_handle = await create_checkpointer(settings)
    intent_service, consolidation, capability_index = build_intent_service(
        settings,
        mcp_registry,
        session_service=session_service,
        mcp_tool_call_repository=mcp_tool_call_repository,
        hitl_service=hitl_service,
        kill_switch=kill_switch,
        redis_client=redis_client,
        session_factory=session_factory,
        dialog_turn_store=dialog_turn_store,
        memory_port=memory_port,
        checkpointer=checkpointer_handle.saver,
    )
    hitl_service.bind_deny_resume(intent_service)

    background_tasks.append(
        asyncio.create_task(
            warm_mcp_capability_cache(capability_index),
            name="mcp-capability-warm",
        )
    )
    logger.info("MCP capability cache warm scheduled")

    background_tasks.append(
        asyncio.create_task(
            _hitl_sweep_loop(hitl_service),
            name="hitl-ttl-sweep",
        )
    )
    logger.info("HITL TTL sweep started", interval_seconds=_HITL_SWEEP_INTERVAL_SECONDS)

    if consolidation is not None:
        background_tasks.append(
            asyncio.create_task(
                consolidation.run_worker(),
                name="memory-consolidation",
            )
        )
        logger.info("Memory consolidation worker started")

    return AppResources(
        settings=settings,
        mcp_registry=mcp_registry,
        intent_service=intent_service,
        session_service=session_service,
        hitl_service=hitl_service,
        kill_switch=kill_switch,
        db_engine=db_engine,
        mcp_tool_call_repository=mcp_tool_call_repository,
        redis_client=redis_client,
        dialog_turn_store=dialog_turn_store,
        memory_port=memory_port,
        consolidation=consolidation,
        checkpointer_handle=checkpointer_handle,
        background_tasks=tuple(background_tasks),
    )


async def _hitl_sweep_loop(hitl_service: HitlService) -> None:
    """Периодически закрывает просроченные HITL-карточки."""
    while True:
        try:
            await asyncio.sleep(_HITL_SWEEP_INTERVAL_SECONDS)
            stats = await hitl_service.sweep_expired()
            if stats["escalated"] or stats["auto_rejected"] or stats.get("dead_letter"):
                logger.info(
                    "HITL sweep closed cards",
                    escalated=stats["escalated"],
                    auto_rejected=stats["auto_rejected"],
                    dead_letter=stats.get("dead_letter", 0),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("HITL sweep failed", error=str(exc))


async def shutdown(resources: AppResources) -> None:
    """Корректно освобождает ресурсы приложения."""
    logger.info("Shutting down...")
    if resources.consolidation is not None:
        with contextlib.suppress(Exception):
            await resources.consolidation.stop()
    if resources.checkpointer_handle is not None and resources.checkpointer_handle.aclose is not None:
        with contextlib.suppress(Exception):
            await resources.checkpointer_handle.aclose()
    for task in resources.background_tasks:
        task.cancel()
    for task in resources.background_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await resources.mcp_registry.close()
    await resources.db_engine.dispose()
    await resources.redis_client.aclose()
    if resources.memory_port is not None:
        closer = getattr(resources.memory_port, "aclose", None)
        if closer is not None:
            with contextlib.suppress(Exception):
                await closer()
    logger.info("Goodbye")
