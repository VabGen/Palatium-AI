# src/palatium_ai/domain/memory/__init__.py

"""Dialog + long-term memory contracts (chat log ≠ memory)."""

from .budget import DEFAULT_PROMPT_BUDGET, MemoryPromptBudget, clip_memory_hints
from .contextualizer import (
    ContextualizerInput,
    ContextualizerOutput,
    ContextualizerTaskResult,
    ContinuationKind,
)
from .continuity import ContinuityPolicy, EffectiveRoutingIntent
from .namespaces import org_namespace, thread_namespace, user_namespace
from .ports import DialogTurnStore, MemoryPort
from .recall import MemoryHit, MemoryRecallBundle
from .turns import DialogRole, DialogTurn, DialogTurnWindow

__all__ = [
    "DEFAULT_PROMPT_BUDGET",
    "ContinuationKind",
    "ContinuityPolicy",
    "ContextualizerInput",
    "ContextualizerOutput",
    "ContextualizerTaskResult",
    "DialogRole",
    "DialogTurn",
    "DialogTurnStore",
    "DialogTurnWindow",
    "EffectiveRoutingIntent",
    "MemoryHit",
    "MemoryPort",
    "MemoryPromptBudget",
    "MemoryRecallBundle",
    "clip_memory_hints",
    "org_namespace",
    "thread_namespace",
    "user_namespace",
]
