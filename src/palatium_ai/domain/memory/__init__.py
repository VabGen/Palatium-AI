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
from .extract_queue import ExtractJobQueuePort, ExtractJobRecord, ExtractQueueStats
from .namespaces import org_namespace, thread_namespace, user_namespace
from .ports import DialogTurnStore, MemoryPort
from .promotion import PromotionCandidate, PromotionThresholds
from .promotion_port import MemoryPromotionPort
from .recall import MemoryHit, MemoryRecallBundle
from .scoring import (
    ImportanceInputs,
    compute_importance,
    frequency_score,
    merge_hybrid_memory_hits,
    rank_by_search_importance,
    recency_score,
)
from .scratchpad import ScratchpadSlot, ScratchpadSlotKind, SessionScratchpad
from .turns import (
    ATTACHMENT_IDS_PAYLOAD_KEY,
    DialogRole,
    DialogTurn,
    DialogTurnWindow,
    attachment_ids_payload,
    parse_turn_attachment_ids,
)
from .types import (
    MEMORY_EXPLICIT_WRITE_KEY,
    MEMORY_ORIGIN_KEY,
    MEMORY_TRUST_KEY,
    MemoryOrigin,
    MemoryTrust,
    MemoryType,
    resolve_memory_origin,
    resolve_memory_trust,
)

__all__ = [
    "ATTACHMENT_IDS_PAYLOAD_KEY",
    "DEFAULT_PROMPT_BUDGET",
    "MEMORY_EXPLICIT_WRITE_KEY",
    "MEMORY_ORIGIN_KEY",
    "MEMORY_TRUST_KEY",
    "CompactMethod",
    "CompactRequest",
    "CompactResult",
    "ContextualizerInput",
    "ContextualizerOutput",
    "ContextualizerTaskResult",
    "ContinuationKind",
    "ContinuityPolicy",
    "DialogRole",
    "DialogTurn",
    "DialogTurnStore",
    "DialogTurnWindow",
    "EffectiveRoutingIntent",
    "ExtractJobQueuePort",
    "ExtractJobRecord",
    "ExtractQueueStats",
    "ImportanceInputs",
    "MemoryHit",
    "MemoryOrigin",
    "MemoryPort",
    "MemoryPromotionPort",
    "MemoryPromptBudget",
    "MemoryRecallBundle",
    "MemoryTrust",
    "MemoryType",
    "PromotionCandidate",
    "PromotionThresholds",
    "ScratchpadSlot",
    "ScratchpadSlotKind",
    "SessionScratchpad",
    "attachment_ids_payload",
    "clip_memory_hints",
    "compute_importance",
    "frequency_score",
    "merge_hybrid_memory_hits",
    "org_namespace",
    "parse_turn_attachment_ids",
    "rank_by_search_importance",
    "recency_score",
    "resolve_memory_origin",
    "resolve_memory_trust",
    "thread_namespace",
    "user_namespace",
]
