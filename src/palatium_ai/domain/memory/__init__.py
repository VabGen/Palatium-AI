# src/palatium_ai/domain/memory/__init__.py

"""Dialog + long-term memory contracts (chat log ≠ memory)."""

from palatium_ai.domain.policies import ContinuityPolicy, EffectiveRoutingIntent

from .budget import DEFAULT_PROMPT_BUDGET, MemoryPromptBudget, clip_memory_hints
from .compact import CompactMethod, CompactRequest, CompactResult
from .contextualizer import (
    ContextualizerInput,
    ContextualizerOutput,
    ContextualizerTaskResult,
    ContinuationKind,
)
from .namespaces import org_namespace, thread_namespace, user_namespace
from .ports import DialogTurnStore, MemoryPort
from .promotion import PromotionCandidate, PromotionThresholds
from .promotion_port import MemoryPromotionPort
from .recall import MemoryHit, MemoryRecallBundle
from .scoring import ImportanceInputs, compute_importance, frequency_score, recency_score
from .scratchpad import ScratchpadSlot, ScratchpadSlotKind, SessionScratchpad
from .turns import DialogRole, DialogTurn, DialogTurnWindow
from .types import MemoryType

__all__ = [
    "DEFAULT_PROMPT_BUDGET",
    "CompactMethod",
    "CompactRequest",
    "CompactResult",
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
    "MemoryPromotionPort",
    "MemoryPromptBudget",
    "MemoryRecallBundle",
    "MemoryType",
    "PromotionCandidate",
    "PromotionThresholds",
    "ScratchpadSlot",
    "ScratchpadSlotKind",
    "SessionScratchpad",
    "ImportanceInputs",
    "compute_importance",
    "frequency_score",
    "recency_score",
    "clip_memory_hints",
    "org_namespace",
    "thread_namespace",
    "user_namespace",
]
