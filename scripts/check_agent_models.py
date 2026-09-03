# scripts/check_agent_models.py

"""Печатает LLM binding для каждого агента (без сетевых вызовов).

Учитывает цепочку: AgentConfig.llm_model → LLM_TIER_* → *_DEFAULT_MODEL.
"""

from __future__ import annotations

from palatium_ai.application.agents.context_enricher import (
    CONTEXT_WEAVER_CONFIG,
    CONTEXTUALIZER_CONFIG,
    ContextualizerAgent,
    ContextWeaverAgent,
)
from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.application.agents.formatter import FORMATTER_CONFIG, FormatterAgent
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.llm.factory import (
    LLMClientFactory,
    _AgentModelLLMAdapter,
    _FallbackChainLLMAdapter,
)


def main() -> None:
    """Проверяет LLM binding для каждого агента (без сетевых вызовов)."""
    settings = get_settings()
    factory = LLMClientFactory(settings)
    configs = {
        ContextualizerAgent: CONTEXTUALIZER_CONFIG,
        ContextWeaverAgent: CONTEXT_WEAVER_CONFIG,
        IntentClassifierAgent: INTENT_CLASSIFIER_CONFIG,
        SupervisorAgent: SUPERVISOR_CONFIG,
        ResearcherAgent: RESEARCHER_CONFIG,
        CriticAgent: CRITIC_CONFIG,
        FormatterAgent: FORMATTER_CONFIG,
        MemoryKeeperAgent: MEMORY_KEEPER_CONFIG,
    }

    print(f"default_provider = {settings.llm.default_provider}")
    print(f"default_model    = {settings.llm.get_active_provider().get_default_model()}")
    print(f"fallback_chain   = {settings.llm.fallback_provider_list or '(none)'}")
    print()
    print("tiers:")
    for tier_name in ("nano", "small", "mid", "frontier", "deep_reasoning"):
        binding = settings.llm.resolve_tier_binding(tier_name)
        print(f"  {tier_name:15} provider={binding.provider!s:8} model={binding.model}")
    print()

    for agent_cls, cfg in configs.items():
        _ = agent_cls
        tier = settings.llm.resolve_tier_binding(cfg.model_tier)
        provider = cfg.llm_provider or tier.provider or settings.llm.default_provider
        provider_cfg = getattr(settings.llm, provider)
        effective_model = cfg.llm_model or tier.model or provider_cfg.get_default_model()
        if cfg.llm_model:
            source = "AgentConfig.llm_model"
        elif tier.model:
            source = f"LLM_TIER_{cfg.model_tier.upper()}_MODEL"
        else:
            source = f"{provider}_DEFAULT_MODEL"

        client = factory.get_client_for_agent(cfg)
        if isinstance(client, _FallbackChainLLMAdapter):
            client_kind = "fallback_chain"
        elif isinstance(client, _AgentModelLLMAdapter):
            client_kind = "tier_wrap"
        else:
            client_kind = "raw"

        print(
            f"{cfg.name:20} tier={cfg.model_tier:14} "
            f"provider={provider:8} model={effective_model}  "
            f"source={source}  client={client_kind}",
        )


if __name__ == "__main__":
    main()
