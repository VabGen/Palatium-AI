# src/palatium_ai/application/wiring.py

"""Composition root: сборка сервисов application-слоя."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from langgraph.checkpoint.memory import MemorySaver

from palatium_ai.application.agents.analyst import ANALYST_CONFIG, AnalystAgent
from palatium_ai.application.agents.coder import CODER_CONFIG, CoderAgent
from palatium_ai.application.agents.context_enricher import (
    CONTEXT_WEAVER_CONFIG,
    CONTEXTUALIZER_CONFIG,
    ContextualizerAgent,
    ContextWeaverAgent,
)
from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.application.agents.formatter import FORMATTER_CONFIG, FormatterAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.application.services.attachment_service import AttachmentService
from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.application.services.cost_budget import CostBudgetService
from palatium_ai.application.services.dialog_compact_summarizer import LlmDialogSummarizer
from palatium_ai.application.services.document_ingest_service import DocumentIngestService
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.memory_extract import MemoryExtractService
from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
from palatium_ai.application.services.memory_write_service import MemoryWriteService
from palatium_ai.application.services.option_synthesizer import OptionSynthesizer
from palatium_ai.application.services.response_cache_service import ResponseCacheService
from palatium_ai.application.services.retention import retention_windows_from_settings
from palatium_ai.application.services.session_service import SessionService
from palatium_ai.core.logging import logger
from palatium_ai.domain.attachments.policies import AttachmentLimits
from palatium_ai.domain.mcp.timeout_policy import (
    McpAgentBudget,
    assert_tool_timeouts_within_agent_budget,
    mcp_tool_keys,
)
from palatium_ai.infrastructure.blob.factory import build_blob_store
from palatium_ai.infrastructure.blob.minio_adapter import MinIOAdapter
from palatium_ai.infrastructure.cache.response_cache import InMemoryResponseCache, RedisResponseCache
from palatium_ai.infrastructure.database.attachment_repository import PostgresAttachmentRepository
from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
from palatium_ai.infrastructure.embeddings.factory import create_embedding_client_for_schema
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.hitl.redis_store import RedisHitlCardStore
from palatium_ai.infrastructure.llm.cost import estimate_completion_cost_usd
from palatium_ai.infrastructure.llm.factory import LLMClientFactory
from palatium_ai.infrastructure.memory.checkpoint_serde import build_checkpoint_serde
from palatium_ai.infrastructure.memory.dialog_turn_store import PostgresDialogTurnStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort
from palatium_ai.infrastructure.parsing.factory import build_document_parser
from palatium_ai.infrastructure.scanning.factory import build_malware_scanner
from palatium_ai.infrastructure.skills.filesystem_skill_catalog import FilesystemSkillCatalog

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.application.services.kill_switch import KillSwitchService
    from palatium_ai.core.config.security import SecurityConfig
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort
    from palatium_ai.domain.ports.blob_store import BlobStorePort
    from palatium_ai.domain.ports.document_parser import DocumentParserPort
    from palatium_ai.domain.ports.mcp import McpToolCallRecorderPort
    from palatium_ai.domain.ports.scanner import MalwareScannerPort
    from palatium_ai.infrastructure.mcp.registry import MCPRegistry


_AGENT_CONFIGS = (
    INTENT_CLASSIFIER_CONFIG,
    CONTEXTUALIZER_CONFIG,
    CONTEXT_WEAVER_CONFIG,
    CRITIC_CONFIG,
    FORMATTER_CONFIG,
    RESEARCHER_CONFIG,
    CODER_CONFIG,
    ANALYST_CONFIG,
    SUPERVISOR_CONFIG,
    MEMORY_KEEPER_CONFIG,
    TEXT_INGESTOR_CONFIG,
)

# Per-tool MCP timeouts must stay below the budget of every agent that may call the tool (070).
_MCP_AGENT_BUDGETS = tuple(
    McpAgentBudget(
        name=config.name,
        timeout_seconds=config.timeout_seconds,
        tools=mcp_tool_keys(config.allowed_tools),
    )
    for config in _AGENT_CONFIGS
)


def _assert_mcp_timeout_budget(settings: Settings) -> None:
    """Fail startup when a configured MCP timeout can outlive its calling agent (070)."""
    mcp = settings.mcp
    if not getattr(mcp, "enabled", True):
        return
    assert_tool_timeouts_within_agent_budget(
        default_timeout_seconds=int(mcp.timeout_seconds),
        tool_timeouts=dict(getattr(mcp, "tool_timeouts", {})),
        agent_budgets=_MCP_AGENT_BUDGETS,
    )


def build_hitl_service(
    *,
    redis_client: Redis | None = None,
    signing_secret: str,
    manager_roles: frozenset[str] | tuple[str, ...] = frozenset({"manager", "admin"}),
    require_shared_store: bool = False,
    step_up_required: bool = False,
    security: SecurityConfig | None = None,
    notify_webhook_url: str | None = None,
    notify_webhook_timeout_seconds: float = 5.0,
) -> HitlService:
    """Создаёт HitlService: Redis store если клиент передан, иначе in-memory.

    Staging/production must pass ``require_shared_store=True`` so HITL/kill-switch
    state cannot silently diverge across workers.
    """
    from palatium_ai.domain.hitl.notify import HitlNotifierPort
    from palatium_ai.domain.hitl.step_up import HitlStepUpProviderPort, HmacHitlStepUpVerifier
    from palatium_ai.infrastructure.hitl.email_notifier import EmailHitlNotifier
    from palatium_ai.infrastructure.hitl.idp_acr_step_up import IdpAcrHitlStepUpProvider
    from palatium_ai.infrastructure.hitl.logging_notifier import LoggingHitlNotifier
    from palatium_ai.infrastructure.hitl.slack_notifier import SlackHitlNotifier
    from palatium_ai.infrastructure.hitl.step_up_jwt import StepUpJwtDecoder
    from palatium_ai.infrastructure.hitl.webhook_notifier import (
        CompositeHitlNotifier,
        WebhookHitlNotifier,
    )

    channels: list[HitlNotifierPort] = [LoggingHitlNotifier()]
    webhook = (notify_webhook_url or "").strip()
    if security is not None and security.hitl_notify_webhook_url is not None:
        webhook = str(security.hitl_notify_webhook_url)
        notify_webhook_timeout_seconds = security.hitl_notify_webhook_timeout_seconds
    if webhook:
        channels.append(WebhookHitlNotifier(webhook, timeout_seconds=notify_webhook_timeout_seconds))

    if security is not None:
        recipients = security.hitl_notify_email_recipients
        if recipients and security.hitl_notify_smtp_host.strip() and security.hitl_notify_email_from.strip():
            password = (
                security.hitl_notify_smtp_password.get_secret_value()
                if security.hitl_notify_smtp_password is not None
                else None
            )
            channels.append(
                EmailHitlNotifier(
                    host=security.hitl_notify_smtp_host,
                    port=security.hitl_notify_smtp_port,
                    mail_from=security.hitl_notify_email_from,
                    mail_to=recipients,
                    username=security.hitl_notify_smtp_username or None,
                    password=password,
                    use_tls=security.hitl_notify_smtp_use_tls,
                )
            )
        slack_token = (
            security.hitl_notify_slack_bot_token.get_secret_value().strip()
            if security.hitl_notify_slack_bot_token is not None
            else ""
        )
        slack_channel = security.hitl_notify_slack_channel.strip()
        if slack_token and slack_channel:
            channels.append(
                SlackHitlNotifier(
                    bot_token=slack_token,
                    channel=slack_channel,
                    timeout_seconds=notify_webhook_timeout_seconds,
                )
            )

    channel_names = ", ".join(type(c).__name__ for c in channels)
    logger.info("HITL notifier channels", channels=channel_names)
    notifier = CompositeHitlNotifier(channels)

    step_up_provider: HitlStepUpProviderPort
    method = security.hitl_step_up_method if security is not None else "hmac_stub"
    if method in {"idp_acr", "webauthn"}:
        if security is None:
            raise RuntimeError("IdP/WebAuthn step-up requires SecurityConfig")
        idp_method: Literal["idp_acr", "webauthn"] = "webauthn" if method == "webauthn" else "idp_acr"
        step_up_provider = IdpAcrHitlStepUpProvider(
            method=idp_method,
            decode_claims=StepUpJwtDecoder(security),
            required_acr=security.hitl_step_up_acr_set,
            required_amr=security.hitl_step_up_amr_set,
            card_claim=security.hitl_step_up_card_claim,
            max_age_seconds=security.hitl_step_up_max_age_seconds,
            authorize_url_template=security.hitl_step_up_authorize_url,
        )
        logger.info("HITL step-up provider", method=method)
    else:
        step_up_provider = HmacHitlStepUpVerifier(signing_secret)
        logger.info("HITL step-up provider", method="hmac_stub")

    if redis_client is not None:
        logger.info("HITL store: Redis")
        return HitlService(
            RedisHitlCardStore(redis_client),
            signing_secret=signing_secret,
            manager_roles=manager_roles,
            step_up_required=step_up_required,
            step_up_provider=step_up_provider,
            notifier=notifier,
        )
    if require_shared_store:
        raise RuntimeError(
            "HITL/kill-switch/budget require a shared Redis store when "
            "ENVIRONMENT is staging or production (refuse in-memory fallback)"
        )
    logger.warning("HITL store: in-memory (not shared across workers)")
    return HitlService(
        InMemoryHitlCardStore(),
        signing_secret=signing_secret,
        manager_roles=manager_roles,
        step_up_required=step_up_required,
        step_up_provider=step_up_provider,
        notifier=notifier,
    )


def build_intent_service(
    settings: Settings,
    mcp_registry: MCPRegistry,
    *,
    session_service: SessionService,
    mcp_tool_call_repository: McpToolCallRepository,
    hitl_service: HitlService,
    kill_switch: KillSwitchService | None = None,
    redis_client: Redis | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    dialog_turn_store: DialogTurnStore | None = None,
    memory_port: MemoryPort | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    enable_sleep_time: bool = True,
    graph_write: GraphWritePort | None = None,
    attachment_service: AttachmentService | None = None,
) -> tuple[IntentService, MemoryExtractService | None, MCPCapabilityIndex, DocumentIngestService]:
    """Создаёт IntentService + optional sleep-time extract worker handle."""
    llm_factory = LLMClientFactory(settings)
    _assert_mcp_timeout_budget(settings)

    resolved_dialog_store = dialog_turn_store
    if resolved_dialog_store is None and session_factory is not None:
        resolved_dialog_store = PostgresDialogTurnStore(session_factory)
        logger.info("Dialog turn store: Postgres")
    elif resolved_dialog_store is None:
        logger.warning("Dialog turn store: disabled")

    resolved_memory = memory_port
    if resolved_memory is None and session_factory is not None:
        embedding_client = None
        try:
            embedding_client = create_embedding_client_for_schema(settings, "memory")
        except Exception as exc:
            logger.warning("Memory embeddings disabled", error=str(exc))
        resolved_memory = PostgresMemoryPort(
            session_factory,
            embeddings=embedding_client,
            retention_windows=retention_windows_from_settings(settings),
            hybrid_fusion=settings.memory.hybrid_fusion,
            rrf_k=settings.memory.rrf_k,
            half_life_days=settings.memory.importance_half_life_days,
        )
        logger.info(
            "MemoryPort: Postgres memory.entries",
            vector_search=embedding_client is not None,
        )
    elif resolved_memory is None:
        resolved_memory = InMemoryMemoryPort()
        logger.info("MemoryPort: in-process (dev/tests)")

    cost_budget = CostBudgetService(
        turn_budget_usd=settings.observability.turn_cost_budget_usd,
        daily_budget_usd=settings.observability.daily_cost_budget_usd,
        redis_client=redis_client,
    )

    resolved_checkpointer = checkpointer if checkpointer is not None else MemorySaver(serde=build_checkpoint_serde())
    compact_summarizer = LlmDialogSummarizer(
        llm_factory.get_client_for_agent(CONTEXTUALIZER_CONFIG),
        model=CONTEXTUALIZER_CONFIG.llm_model,
    )
    memory_writer = MemoryWriteService(resolved_memory)
    skill_catalog = FilesystemSkillCatalog(
        settings.skills.roots,
        reference_max_chars=settings.skills.reference_max_chars,
    )
    context_builder = ContextBuilder(
        dialog_store=resolved_dialog_store,
        memory_port=resolved_memory,
        memory_writer=memory_writer,
        summarizer=compact_summarizer,
        skill_catalog=skill_catalog,
        skill_catalog_max_chars=settings.skills.catalog_max_chars,
    )
    harness = Harness(
        context_builder=context_builder,
        llm_factory=llm_factory,
        cost_budget=cost_budget,
        cost_estimator=estimate_completion_cost_usd,
    )
    intent_agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    continuation = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    capability_index = MCPCapabilityIndex(mcp_registry)
    weaving = ContextWeaverAgent(
        harness,
        CONTEXT_WEAVER_CONFIG,
        mcp_registry=mcp_registry,
        capability_index=capability_index,
    )
    critic = CriticAgent(harness, CRITIC_CONFIG)
    formatter = FormatterAgent(harness, FORMATTER_CONFIG)
    option_synthesizer = OptionSynthesizer(
        llm_factory.get_client_for_agent(INTENT_CLASSIFIER_CONFIG),
    )
    researcher = ResearcherAgent(
        harness,
        RESEARCHER_CONFIG,
        llm_factory.get_client_for_agent(RESEARCHER_CONFIG),
        mcp_registry=mcp_registry,
        mcp_tool_call_repository=mcp_tool_call_repository,
        capability_index=capability_index,
    )
    # Composition root (000): construct the roster; the graph builder itself is
    # agent-agnostic and reads node↔agent mapping from the registry (3.2).
    graph = build_agent_graph(
        GraphAgents(
            intent_agent=intent_agent,
            supervisor_agent=SupervisorAgent(harness, SUPERVISOR_CONFIG),
            continuation_agent=continuation,
            weaving_agent=weaving,
            researcher_agent=researcher,
            coder_agent=CoderAgent(harness, CODER_CONFIG),
            analyst_agent=AnalystAgent(harness, ANALYST_CONFIG),
            critic_agent=critic,
            formatter_agent=formatter,
        ),
        harness=harness,
        checkpointer=resolved_checkpointer,
    )

    memory_extract: MemoryExtractService | None = None
    if enable_sleep_time:
        from palatium_ai.infrastructure.memory.extract_job_queue import (
            InMemoryExtractJobQueue,
            PostgresExtractJobQueue,
        )

        memory_keeper = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
        memory_persistence = MemoryFactPersistenceService(
            mcp_registry=mcp_registry,
            mcp_tool_call_repository=mcp_tool_call_repository,
        )
        # Promote is out-of-band only: ``python -m palatium_ai.jobs.memory_promote`` (M3).
        if settings.memory.promote_enabled and hasattr(resolved_memory, "bump_access"):
            logger.info(
                "Memory promotion: CronJob/one-shot only (decoupled from extract)",
                min_access_frequency=settings.memory.promote_min_access_frequency,
                min_importance=settings.memory.promote_min_importance,
            )
        extract_queue = (
            PostgresExtractJobQueue(session_factory) if session_factory is not None else InMemoryExtractJobQueue()
        )
        memory_extract = MemoryExtractService(
            harness=harness,
            memory_keeper=memory_keeper,
            memory_port=resolved_memory,
            memory_persistence=memory_persistence,
            job_queue=extract_queue,
            dialog_turn_store=resolved_dialog_store,
        )
        logger.info(
            "Memory extract: durable SKIP LOCKED queue enabled",
            queue=type(extract_queue).__name__,
        )

    text_ingestor = TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG)
    document_ingest = DocumentIngestService(
        harness=harness,
        text_ingestor=text_ingestor,
        hitl_service=hitl_service,
        mcp_registry=mcp_registry,
        redis_client=redis_client,
        mcp_tool_call_repository=mcp_tool_call_repository,
    )
    logger.info("Document ingest: TextIngestor service enabled")

    cache_port = RedisResponseCache(redis_client) if redis_client is not None else InMemoryResponseCache()
    response_cache = ResponseCacheService(
        cache_port,
        ttl_seconds=settings.observability.response_cache_ttl_seconds,
        enabled=settings.observability.response_cache_enabled,
    )
    if settings.observability.response_cache_enabled:
        logger.info(
            "L1 response cache enabled",
            backend="redis" if redis_client is not None else "memory",
            ttl_seconds=settings.observability.response_cache_ttl_seconds,
        )

    intent_service = IntentService(
        graph,
        session_service=session_service,
        hitl_service=hitl_service,
        kill_switch=kill_switch,
        cost_budget=cost_budget,
        dialog_turn_store=resolved_dialog_store,
        memory_port=resolved_memory,
        consolidation=memory_extract,
        option_synthesizer=option_synthesizer,
        recall_min_confidence=settings.memory.recall_min_confidence,
        recall_max_items=settings.memory.recall_max_items,
        recall_max_chars=settings.memory.recall_max_chars,
        contextualizer_dialog_max_chars=settings.memory.contextualizer_dialog_max_chars,
        worker_summary_max_chars=settings.memory.worker_summary_max_chars,
        mcp_tool_output_max_chars=settings.memory.mcp_tool_output_max_chars,
        turn_hop_budget_ms=settings.observability.turn_hop_budget_ms,
        attachment_service=attachment_service,
        response_cache=response_cache,
    )
    return intent_service, memory_extract, capability_index, document_ingest


async def warm_mcp_capability_cache(index: MCPCapabilityIndex) -> None:
    """Background prefetch of MCP capability index (startup, non-blocking for requests)."""
    try:
        count = await index.warm_cache()
        logger.info("MCP capability cache warmed", bindings=count)
    except Exception as exc:
        logger.warning("MCP capability cache warm failed", error=str(exc))


@dataclass(frozen=True, slots=True)
class AttachmentPorts:
    """Attachment infrastructure ports; built only when the subsystem is enabled."""

    repository: AttachmentRepositoryPort
    blob_store: BlobStorePort
    malware_scanner: MalwareScannerPort
    document_parser: DocumentParserPort


async def build_attachment_ports(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> AttachmentPorts | None:
    """Build the attachment ports, or ``None`` when the feature is disabled (000).

    This is where the fail-closed configuration guards actually run: an in-process
    blob store or a disabled AV scanner outside local/test aborts startup here,
    rather than on the first upload (020). A MinIO backend is also probed now, so
    a wrong endpoint fails the boot instead of the first user request.
    """
    if not settings.attachments.enabled:
        logger.info("Attachments disabled (ATTACHMENTS_ENABLED=false)")
        return None

    blob_store = build_blob_store(settings)
    if isinstance(blob_store, MinIOAdapter):
        already_present = await blob_store.ensure_bucket()
        logger.info("Attachment bucket ready", created=not already_present)

    ports = AttachmentPorts(
        repository=PostgresAttachmentRepository(session_factory),
        blob_store=blob_store,
        malware_scanner=build_malware_scanner(settings),
        document_parser=build_document_parser(settings),
    )
    logger.info("Attachment ports wired", blob_backend=settings.attachments.blob_backend)
    return ports


def build_attachment_limits(settings: Settings) -> AttachmentLimits:
    """Map flat ``AttachmentConfig`` values onto the domain value object (010).

    ``core`` cannot import ``domain``, so the composition root owns this
    translation; keeping it in one function means the router, pipeline and
    repository can never disagree about a limit (050).
    """
    cfg = settings.attachments
    return AttachmentLimits(
        max_size_bytes=cfg.max_size_bytes,
        max_chunk_bytes=cfg.max_chunk_bytes,
        max_attachments_per_turn=cfg.max_attachments_per_turn,
        max_filename_chars=cfg.max_filename_chars,
        presigned_url_ttl_seconds=cfg.presigned_url_ttl_seconds,
        attach_ttl_seconds=cfg.attach_ttl_seconds,
        index_retention_days=cfg.index_retention_days,
        retention_sweep_batch=cfg.sweep_batch_size,
    )


def build_attachment_service(
    settings: Settings,
    ports: AttachmentPorts,
    *,
    hitl_service: HitlService,
    mcp_registry: MCPRegistry,
    redis_client: Redis | None = None,
    mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
    document_ingest_service: DocumentIngestService | None = None,
) -> AttachmentService:
    """Build the attachment use-case layer over probed ports (000).

    Requires an already-constructed ``HitlService``: indexing user files into the
    durable knowledge base is a write-side effect and must mint a one-shot card
    before ``platform.ingest_document`` runs (020, 070).
    """
    limits = build_attachment_limits(settings)
    pipeline = AttachmentPipeline(
        blob_store=ports.blob_store,
        malware_scanner=ports.malware_scanner,
        document_parser=ports.document_parser,
        pii_policy=settings.attachments.pii_policy,
    )
    from palatium_ai.infrastructure.analysis import (
        DisabledAttachmentAnalysis,
        LocalDataframeAttachmentAnalysis,
    )
    from palatium_ai.infrastructure.connectors import DisabledAttachmentConnector

    analysis = (
        LocalDataframeAttachmentAnalysis()
        if settings.attachments.analysis_backend == "local"
        else DisabledAttachmentAnalysis()
    )
    logger.info(
        "AttachmentService wired",
        blob_backend=settings.attachments.blob_backend,
        scanner_backend=settings.attachments.scanner_backend,
        analysis_backend=settings.attachments.analysis_backend,
        max_per_turn=limits.max_attachments_per_turn,
        index_enrich=document_ingest_service is not None,
    )
    return AttachmentService(
        repository=ports.repository,
        blob_store=ports.blob_store,
        pipeline=pipeline,
        hitl_service=hitl_service,
        mcp_registry=mcp_registry,
        redis_client=redis_client,
        mcp_tool_call_repository=mcp_tool_call_repository,
        document_ingest_service=document_ingest_service,
        analysis=analysis,
        connector=DisabledAttachmentConnector(),
        limits=limits,
    )
