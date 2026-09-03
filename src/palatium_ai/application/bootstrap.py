# src/palatium_ai/application/bootstrap.py

"""Инициализация и завершение ресурсов приложения."""

from __future__ import annotations

import asyncio
import contextlib
import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from palatium_ai.application.services.document_export_service import DocumentExportService
from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.application.services.memory_consolidate_service import MemoryConsolidateService
from palatium_ai.application.services.memory_forget_service import MemoryForgetService
from palatium_ai.application.services.memory_save_service import MemorySaveService
from palatium_ai.application.services.session_service import SessionService
from palatium_ai.application.services.session_timeline_service import SessionTimelineService
from palatium_ai.application.wiring import build_hitl_service, build_intent_service, warm_mcp_capability_cache
from palatium_ai.core.logging import logger, setup_logging
from palatium_ai.core.observability import setup_observability
from palatium_ai.infrastructure.cache.redis import create_redis_client, ensure_redis_connection
from palatium_ai.infrastructure.database.init_db import (
    ensure_database_and_schema,
)
from palatium_ai.infrastructure.database.repositories import (
    McpToolCallRepository,
    SessionRepository,
)
from palatium_ai.infrastructure.database.runtime import create_session_factory
from palatium_ai.infrastructure.embeddings.factory import create_embedding_client_for_schema
from palatium_ai.infrastructure.graph.factory import build_graph_port
from palatium_ai.infrastructure.knowledge.postgres_knowledge_port import PostgresKnowledgePort
from palatium_ai.infrastructure.mcp.consul_source import ConsulMCPSource
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
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
from palatium_ai.infrastructure.web.factory import build_web_search_port

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine

    from palatium_ai.application.services.document_ingest_service import DocumentIngestService
    from palatium_ai.application.services.intent_service import IntentService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.graph.port import GraphPort
    from palatium_ai.domain.knowledge.port import KnowledgePort
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort
    from palatium_ai.domain.web.port import WebSearchPort

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
    document_ingest_service: DocumentIngestService | None = None
    memory_save_service: MemorySaveService | None = None
    memory_forget_service: MemoryForgetService | None = None
    memory_consolidate_service: MemoryConsolidateService | None = None
    checkpointer_handle: CheckpointerHandle | None = None
    background_tasks: tuple[asyncio.Task[None], ...] = field(default_factory=tuple)
    document_export_service: DocumentExportService = field(default_factory=DocumentExportService)
    session_timeline_service: SessionTimelineService | None = None
    hitl_respond_facade: HitlRespondFacade | None = None
    graph_port: GraphPort | None = None
    web_search_port: WebSearchPort | None = None


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
        embedding_client = None
        try:
            embedding_client = create_embedding_client_for_schema(settings, "memory")
        except Exception as exc:
            logger.warning("Memory embeddings disabled", error=str(exc))
        port = PostgresMemoryPort(session_factory, embeddings=embedding_client)  # type: ignore[arg-type]
        logger.info(
            "MemoryPort: Postgres memory.entries",
            vector_search=embedding_client is not None,
        )

    if settings.memory.embedding_rerank and backend == "postgres":
        try:
            rerank_client = create_embedding_client_for_schema(settings, "memory")
            if rerank_client is None:
                raise RuntimeError("no memory-dim embedding provider for rerank")
            port = EmbeddingRerankMemoryPort(port, rerank_client)
            logger.info("MemoryPort: Postgres + embedding rerank")
        except Exception as exc:
            logger.warning("Memory embedding rerank disabled", error=str(exc))
    elif settings.memory.embedding_rerank:
        logger.info("MEMORY_EMBEDDING_RERANK ignored for non-postgres backend", backend=backend)
    return port


def _build_knowledge_port(settings: Settings, session_factory: object) -> KnowledgePort:
    """KnowledgePort for platform.ingest_document (postgres or in-memory fallback)."""
    embedding_client = None
    try:
        embedding_client = create_embedding_client_for_schema(settings, "knowledge")
    except Exception as exc:
        logger.warning("Knowledge embeddings disabled", error=str(exc))
    return PostgresKnowledgePort(session_factory, embeddings=embedding_client)  # type: ignore[arg-type]


def _wire_platform_handler(
    mcp_registry: MCPRegistry,
    knowledge_port: KnowledgePort,
    memory_port: MemoryPort | None = None,
    consolidation: object | None = None,
    *,
    graph_port: GraphPort,
    web_search_port: WebSearchPort,
) -> None:
    if not mcp_registry.is_registered("platform"):
        logger.info("Platform MCP not registered; local handler skipped")
        return
    mcp_registry.register_local_handler(
        "platform",
        PlatformToolHandler(
            knowledge_port=knowledge_port,
            memory_port=memory_port,
            consolidation=consolidation,  # type: ignore[arg-type]
            graph_port=graph_port,
            web_search_port=web_search_port,
        ),
    )
    logger.info("Platform MCP: local knowledge+memory+graph+web handler registered")


async def startup(settings: Settings) -> AppResources:
    """Инициализирует логирование, БД, Redis и MCP-реестр."""
    ensure_psycopg_compatible_loop()
    setup_logging(settings)
    setup_observability(settings)
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

    db_engine, session_factory = create_session_factory(settings)
    knowledge_port = _build_knowledge_port(settings, session_factory)

    background_tasks: list[asyncio.Task[None]] = []
    if source is not None:
        background_tasks.append(asyncio.create_task(source.watch(mcp_registry.reload)))
        logger.info("MCP watch started")

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
    intent_service, consolidation, capability_index, document_ingest_service = build_intent_service(
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
    graph_port = build_graph_port(settings)
    web_search_port = build_web_search_port(settings)
    _wire_platform_handler(
        mcp_registry,
        knowledge_port,
        memory_port,
        consolidation,
        graph_port=graph_port,
        web_search_port=web_search_port,
    )

    session_timeline_service = SessionTimelineService(
        dialog_turn_store=dialog_turn_store,
        mcp_tool_call_repository=mcp_tool_call_repository,
    )
    memory_save_service = MemorySaveService(
        hitl_service=hitl_service,
        mcp_registry=mcp_registry,
        redis_client=redis_client,
        mcp_tool_call_repository=mcp_tool_call_repository,
    )
    memory_forget_service = MemoryForgetService(
        hitl_service=hitl_service,
        mcp_registry=mcp_registry,
        redis_client=redis_client,
        mcp_tool_call_repository=mcp_tool_call_repository,
    )
    memory_consolidate_service: MemoryConsolidateService | None = None
    if consolidation is not None:
        memory_consolidate_service = MemoryConsolidateService(
            hitl_service=hitl_service,
            mcp_registry=mcp_registry,
            redis_client=redis_client,
            mcp_tool_call_repository=mcp_tool_call_repository,
        )
    hitl_respond_facade = HitlRespondFacade(
        hitl_service=hitl_service,
        intent_service=intent_service,
        document_ingest_service=document_ingest_service,
        memory_save_service=memory_save_service,
        memory_forget_service=memory_forget_service,
        memory_consolidate_service=memory_consolidate_service,
    )

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
        document_ingest_service=document_ingest_service,
        memory_save_service=memory_save_service,
        memory_forget_service=memory_forget_service,
        memory_consolidate_service=memory_consolidate_service,
        checkpointer_handle=checkpointer_handle,
        background_tasks=tuple(background_tasks),
        document_export_service=DocumentExportService(),
        session_timeline_service=session_timeline_service,
        hitl_respond_facade=hitl_respond_facade,
        graph_port=graph_port,
        web_search_port=web_search_port,
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


async def _aclose_optional(resource: object | None) -> None:
    """Call ``aclose()`` on a resource when present; swallow close errors."""
    if resource is None:
        return
    closer = getattr(resource, "aclose", None)
    if closer is not None:
        with contextlib.suppress(Exception):
            await closer()


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
    await _aclose_optional(resources.memory_port)
    await _aclose_optional(resources.graph_port)
    await _aclose_optional(resources.web_search_port)
    logger.info("Goodbye")
