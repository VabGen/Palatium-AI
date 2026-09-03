# src/palatium_ai/application/orchestration/state.py

"""Состояние LangGraph для пайплайна агентов."""

from __future__ import annotations

from typing import TypedDict

from palatium_ai.domain.agents.context_weaver import ContextWeaverTaskResult
from palatium_ai.domain.agents.critic import CriticTaskResult
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.agents.researcher import ResearcherTaskResult
from palatium_ai.domain.agents.supervisor import SupervisorTaskResult
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerTaskResult
from palatium_ai.domain.memory.recall import MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import EffectiveRoutingIntent


class AgentGraphState(TypedDict, total=False):
    """Shared state для StateGraph."""

    task_id: str
    user_text: str
    thread_id: str
    user_id: str
    org_id: str
    trace_id: str
    goal: str
    plan: str
    revisions_count: int
    dialog_window: DialogTurnWindow
    memory_recall: MemoryRecallBundle
    prompt_budget: MemoryPromptBudget
    contextualization: ContextualizerTaskResult
    effective_user_text: str
    classification: IntentTaskResult
    routing_intent: EffectiveRoutingIntent
    routing: SupervisorTaskResult
    context_bundle: ContextWeaverTaskResult
    execution: ResearcherTaskResult
    critic: CriticTaskResult
    formatted: FormatterTaskResult
    revision_feedback: str
    requires_clarification: bool
    clarification_question: str
