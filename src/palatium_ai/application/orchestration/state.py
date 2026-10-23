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
from palatium_ai.domain.attachments.context import AttachmentTurnContext
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerTaskResult
from palatium_ai.domain.memory.recall import MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import EffectiveRoutingIntent
from palatium_ai.domain.policies.types import PresentationOwner


class AgentGraphState(TypedDict, total=False):
    """Shared state для StateGraph.

    ``total=False`` is required: LangGraph nodes return *partial* updates that merge
    into checkpointed state. Core keys (``task_id``, ``user_text``, …) are always set
    at ``ainvoke`` — read them via ``selectors`` / ``state_access`` helpers, not bare
    ``state["task_id"]`` (basedpyright KeyError risk on TypedDict).
    """

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
    # Fenced attachment text for this turn (already wrapped by AttachmentService).
    # Never raw file text: the fence is the contract for the prompt (020, 065).
    untrusted_context: str
    # Typed, immutable attachment state for this turn (Level 0). ``untrusted_context``
    # is the projection handed to prompts; this is the SoT for selection, modality
    # filtering and the "attached but unreadable" guard.
    attachment_context: AttachmentTurnContext
    # BCP-47 pin for user-facing replies (ReplyLocalePolicy); sticky across turns via session.
    response_locale: str
    #: The ask deterministically names a file this dialog holds (pre-graph resolution of
    #: the thread attachment registry). Sets the ``thread_file`` axis in ContinuityPolicy.
    thread_file_named: bool
    # Single writer for this turn (PresentationOwnershipPolicy); formatter = safe default.
    presentation_owner: PresentationOwner
    presentation_owner_reason: str
