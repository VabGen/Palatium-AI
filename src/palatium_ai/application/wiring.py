# src/palatium_ai/application/wiring.py

"""Composition root: сборка сервисов application-слоя."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langgraph.checkpoint.memory import MemorySaver

from palatium_ai.application.agents.context_weaver_agent import ContextWeaverAgent
from palatium_ai.application.agents.contextualizer_agent import ContextualizerAgent
from palatium_ai.application.agents.critic_agent import CriticAgent
from palatium_ai.application.agents.formatter_agent import FormatterAgent
from palatium_ai.application.agents.intent_classifier_agent import IntentClassifierAgent
from palatium_ai.application.agents.memory_keeper_agent import MemoryKeeperAgent
from palatium_ai.application.agents.researcher_agent import ResearcherAgent
from palatium_ai.application.agents.supervisor_agent import SupervisorAgent
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.cost_budget import CostBudgetService
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
from palatium_ai.application.services.session_service import SessionService
from palatium_ai.core.logging import logger
from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.hitl.redis_store import RedisHitlCardStore
from palatium_ai.infrastructure.llm.factory import LLMClientFactory
from palatium_ai.infrastructure.memory.checkpoint_serde import build_checkpoint_serde
from palatium_ai.infrastructure.memory.dialog_turn_store import PostgresDialogTurnStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.core.config.security import SecurityConfig
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort
    from palatium_ai.infrastructure.mcp.registry import MCPRegistry


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
) -> tuple[IntentService, MemoryConsolidationService | None, MCPCapabilityIndex]:
    """Создаёт IntentService + optional sleep-time consolidation worker handle."""
    llm_factory = LLMClientFactory(settings)

    resolved_dialog_store = dialog_turn_store
    if resolved_dialog_store is None and session_factory is not None:
        resolved_dialog_store = PostgresDialogTurnStore(session_factory)
        logger.info("Dialog turn store: Postgres")
    elif resolved_dialog_store is None:
        logger.warning("Dialog turn store: disabled")

    resolved_memory = memory_port
    if resolved_memory is None and session_factory is not None:
        resolved_memory = PostgresMemoryPort(session_factory)
        logger.info("MemoryPort: Postgres")
    elif resolved_memory is None:
        resolved_memory = InMemoryMemoryPort()
        logger.info("MemoryPort: in-process (dev/tests)")

    cost_budget = CostBudgetService(
        turn_budget_usd=settings.observability.turn_cost_budget_usd,
        daily_budget_usd=settings.observability.daily_cost_budget_usd,
        redis_client=redis_client,
    )

    agent = IntentClassifierAgent(
        llm_factory.get_client_for_agent(IntentClassifierAgent.config),
        cost_budget=cost_budget,
    )
    contextualizer = ContextualizerAgent(
        llm_factory.get_client_for_agent(ContextualizerAgent.config),
        cost_budget=cost_budget,
    )
    capability_index = MCPCapabilityIndex(mcp_registry)
    context_weaver = ContextWeaverAgent(mcp_registry=mcp_registry, capability_index=capability_index)
    critic = CriticAgent(
        llm_factory.get_client_for_agent(CriticAgent.config),
        cost_budget=cost_budget,
    )
    formatter = FormatterAgent(
        llm_factory.get_client_for_agent(FormatterAgent.config),
        cost_budget=cost_budget,
    )
    researcher = ResearcherAgent(
        llm_factory.get_client_for_agent(ResearcherAgent.config),
        mcp_registry=mcp_registry,
        mcp_tool_call_repository=mcp_tool_call_repository,
        capability_index=capability_index,
        cost_budget=cost_budget,
    )
    supervisor = SupervisorAgent()
    resolved_checkpointer = checkpointer if checkpointer is not None else MemorySaver(serde=build_checkpoint_serde())
    graph = build_agent_graph(
        intent_agent=agent,
        supervisor_agent=supervisor,
        context_weaver_agent=context_weaver,
        researcher_agent=researcher,
        critic_agent=critic,
        formatter_agent=formatter,
        contextualizer_agent=contextualizer,
        checkpointer=resolved_checkpointer,
    )

    consolidation: MemoryConsolidationService | None = None
    if enable_sleep_time:
        memory_keeper = MemoryKeeperAgent(
            llm_factory.get_client_for_agent(MemoryKeeperAgent.config),
            cost_budget=cost_budget,
        )
        consolidation = MemoryConsolidationService(
            memory_keeper=memory_keeper,
            memory_port=resolved_memory,
            dialog_turn_store=resolved_dialog_store,
        )
        logger.info("Memory consolidation: sleep-time queue enabled")

    intent_service = IntentService(
        graph,
        session_service=session_service,
        hitl_service=hitl_service,
        kill_switch=kill_switch,
        cost_budget=cost_budget,
        dialog_turn_store=resolved_dialog_store,
        memory_port=resolved_memory,
        consolidation=consolidation,
        recall_min_confidence=settings.memory.recall_min_confidence,
        recall_max_items=settings.memory.recall_max_items,
        recall_max_chars=settings.memory.recall_max_chars,
        contextualizer_dialog_max_chars=settings.memory.contextualizer_dialog_max_chars,
        worker_summary_max_chars=settings.memory.worker_summary_max_chars,
        mcp_tool_output_max_chars=settings.memory.mcp_tool_output_max_chars,
        turn_hop_budget_ms=settings.observability.turn_hop_budget_ms,
    )
    return intent_service, consolidation, capability_index


async def warm_mcp_capability_cache(index: MCPCapabilityIndex) -> None:
    """Background prefetch of MCP capability index (startup, non-blocking for requests)."""
    try:
        count = await index.warm_cache()
        logger.info("MCP capability cache warmed", bindings=count)
    except Exception as exc:
        logger.warning("MCP capability cache warm failed", error=str(exc))
