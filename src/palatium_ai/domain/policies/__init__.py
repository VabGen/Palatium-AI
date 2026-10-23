# src/palatium_ai/domain/policies/__init__.py

"""Доменные политики и оси (055).

Eager: только types. Политики (ContinuityPolicy и др.) — lazy через __getattr__,
иначе mcp.models → policies → continuity → agents → mcp.models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import (
    GROUNDING_DEFAULT,
    LOW_RISK_ROUTE_STRATEGIES,
    RESPONSE_SHAPE_DEFAULT,
    SUBSTANTIVE_USER_PAYLOAD_CHARS,
    TRANSFORMATION_DEFAULT,
    AgentRole,
    ContinuationKind,
    ExecutionStrategy,
    GroundingMode,
    ModelTier,
    ResponseShape,
    RouteStrategy,
    TaskKind,
    TransformationKind,
    UnderspecificationKind,
    UntrustedContentAction,
)

if TYPE_CHECKING:
    from .ack_reply import AckReplyPolicy
    from .attachment_selection import AttachmentSelection, AttachmentSelectionPolicy
    from .attachment_stickiness import (
        AttachmentRehydrateDecision,
        AttachmentStickinessDecision,
        AttachmentStickinessPolicy,
    )
    from .clarification import CLARIFY_MIN_CONFIDENCE, ClarificationGatePolicy
    from .compact import CompactPolicy
    from .contextualizer import ContextualizerGateDecision, ContextualizerPolicy
    from .continuity import ContinuityPolicy, EffectiveRoutingIntent
    from .critic import CriticGateDecision, CriticPolicy
    from .formatter_fast_path import (
        FormatterFastPathDecision,
        FormatterFastPathPolicy,
        FormatterPassthroughSignals,
    )
    from .formatter_memory_merge import FormatterMemoryMergeDecision, FormatterMemoryMergePolicy
    from .grounding import GroundingEmptyDecision, GroundingPolicy
    from .hop_budget import HopBudgetDecision, HopBudgetPolicy
    from .internal_vocabulary import InternalVocabularyPolicy
    from .locale import ReplyLocalePolicy
    from .memory_namespace import MemoryNamespaceBinding, MemoryNamespacePolicy
    from .memory_recall import MemoryRecallDecision, MemoryRecallPolicy
    from .parallel_workers import ParallelWorkerPolicy, ParallelWorkersDecision
    from .presentation import PresentationOwnershipDecision, PresentationOwnershipPolicy
    from .promotion import PromotionPolicy
    from .researcher_tier import ResearcherTierDecision, ResearcherTierPolicy
    from .response_cache import ResponseCacheKeyParts, ResponseCacheKeyPolicy
    from .retention import RetentionDecision, RetentionPolicy, RetentionWindows
    from .retrieval import LAST_RESORT_PLATFORM_TOOLS, RetrievalBindingDecision, RetrievalPolicy
    from .scratchpad import SessionScratchpadPolicy
    from .shape import ShapeRecipe, ShapeRecipePolicy, ShapeVerdict
    from .transform import TransformPolicy, TransformRouteDecision
    from .untrusted_content import (
        DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
        FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS,
        UntrustedContentPolicy,
        UntrustedContentResult,
        UntrustedContentThresholds,
        budget_untrusted_text,
        count_fence_blocks,
    )

__all__ = [
    "CLARIFY_MIN_CONFIDENCE",
    "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS",
    "FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS",
    "GROUNDING_DEFAULT",
    "LAST_RESORT_PLATFORM_TOOLS",
    "LOW_RISK_ROUTE_STRATEGIES",
    "RESPONSE_SHAPE_DEFAULT",
    "SUBSTANTIVE_USER_PAYLOAD_CHARS",
    "TRANSFORMATION_DEFAULT",
    "AckReplyPolicy",
    "AgentRole",
    "AttachmentRehydrateDecision",
    "AttachmentSelection",
    "AttachmentSelectionPolicy",
    "AttachmentStickinessDecision",
    "AttachmentStickinessPolicy",
    "ClarificationGatePolicy",
    "CompactPolicy",
    "ContextualizerGateDecision",
    "ContextualizerPolicy",
    "ContinuationKind",
    "ContinuityPolicy",
    "CriticGateDecision",
    "CriticPolicy",
    "EffectiveRoutingIntent",
    "ExecutionStrategy",
    "ExtractAdmissionDecision",
    "ExtractAdmissionPolicy",
    "FormatterFastPathDecision",
    "FormatterFastPathPolicy",
    "FormatterMemoryMergeDecision",
    "FormatterMemoryMergePolicy",
    "FormatterPassthroughSignals",
    "GroundingEmptyDecision",
    "GroundingMode",
    "GroundingPolicy",
    "HopBudgetDecision",
    "HopBudgetPolicy",
    "InternalVocabularyPolicy",
    "MemoryNamespaceBinding",
    "MemoryNamespacePolicy",
    "MemoryRecallDecision",
    "MemoryRecallPolicy",
    "ModelTier",
    "ParallelWorkerPolicy",
    "ParallelWorkersDecision",
    "PresentationOwnershipDecision",
    "PresentationOwnershipPolicy",
    "PromotionPolicy",
    "ReplyLocalePolicy",
    "ResearcherTierDecision",
    "ResearcherTierPolicy",
    "ResponseCacheKeyParts",
    "ResponseCacheKeyPolicy",
    "ResponseShape",
    "RetentionDecision",
    "RetentionPolicy",
    "RetentionWindows",
    "RetrievalBindingDecision",
    "RetrievalPolicy",
    "RouteStrategy",
    "SessionScratchpadPolicy",
    "ShapeRecipe",
    "ShapeRecipePolicy",
    "ShapeVerdict",
    "TaskKind",
    "TransformPolicy",
    "TransformRouteDecision",
    "TransformationKind",
    "UnderspecificationKind",
    "UntrustedContentAction",
    "UntrustedContentPolicy",
    "UntrustedContentResult",
    "UntrustedContentThresholds",
    "budget_untrusted_text",
    "count_fence_blocks",
]

_LAZY: dict[str, tuple[str, str]] = {
    "AckReplyPolicy": (".ack_reply", "AckReplyPolicy"),
    "AttachmentSelection": (".attachment_selection", "AttachmentSelection"),
    "AttachmentSelectionPolicy": (".attachment_selection", "AttachmentSelectionPolicy"),
    "AttachmentStickinessPolicy": (".attachment_stickiness", "AttachmentStickinessPolicy"),
    "AttachmentStickinessDecision": (".attachment_stickiness", "AttachmentStickinessDecision"),
    "AttachmentRehydrateDecision": (".attachment_stickiness", "AttachmentRehydrateDecision"),
    "CLARIFY_MIN_CONFIDENCE": (".clarification", "CLARIFY_MIN_CONFIDENCE"),
    "ClarificationGatePolicy": (".clarification", "ClarificationGatePolicy"),
    "CompactPolicy": (".compact", "CompactPolicy"),
    "ContinuityPolicy": (".continuity", "ContinuityPolicy"),
    "EffectiveRoutingIntent": (".continuity", "EffectiveRoutingIntent"),
    "ContextualizerGateDecision": (".contextualizer", "ContextualizerGateDecision"),
    "ContextualizerPolicy": (".contextualizer", "ContextualizerPolicy"),
    "CriticGateDecision": (".critic", "CriticGateDecision"),
    "CriticPolicy": (".critic", "CriticPolicy"),
    "ExtractAdmissionDecision": (".extract_admission", "ExtractAdmissionDecision"),
    "ExtractAdmissionPolicy": (".extract_admission", "ExtractAdmissionPolicy"),
    "FormatterFastPathDecision": (".formatter_fast_path", "FormatterFastPathDecision"),
    "FormatterFastPathPolicy": (".formatter_fast_path", "FormatterFastPathPolicy"),
    "FormatterPassthroughSignals": (".formatter_fast_path", "FormatterPassthroughSignals"),
    "FormatterMemoryMergeDecision": (".formatter_memory_merge", "FormatterMemoryMergeDecision"),
    "FormatterMemoryMergePolicy": (".formatter_memory_merge", "FormatterMemoryMergePolicy"),
    "GroundingEmptyDecision": (".grounding", "GroundingEmptyDecision"),
    "GroundingPolicy": (".grounding", "GroundingPolicy"),
    "HopBudgetDecision": (".hop_budget", "HopBudgetDecision"),
    "HopBudgetPolicy": (".hop_budget", "HopBudgetPolicy"),
    "InternalVocabularyPolicy": (".internal_vocabulary", "InternalVocabularyPolicy"),
    "TransformPolicy": (".transform", "TransformPolicy"),
    "TransformRouteDecision": (".transform", "TransformRouteDecision"),
    "MemoryNamespaceBinding": (".memory_namespace", "MemoryNamespaceBinding"),
    "MemoryNamespacePolicy": (".memory_namespace", "MemoryNamespacePolicy"),
    "MemoryRecallDecision": (".memory_recall", "MemoryRecallDecision"),
    "MemoryRecallPolicy": (".memory_recall", "MemoryRecallPolicy"),
    "ParallelWorkerPolicy": (".parallel_workers", "ParallelWorkerPolicy"),
    "ParallelWorkersDecision": (".parallel_workers", "ParallelWorkersDecision"),
    "PresentationOwnershipDecision": (".presentation", "PresentationOwnershipDecision"),
    "PresentationOwnershipPolicy": (".presentation", "PresentationOwnershipPolicy"),
    "PromotionPolicy": (".promotion", "PromotionPolicy"),
    "ReplyLocalePolicy": (".locale", "ReplyLocalePolicy"),
    "ResearcherTierDecision": (".researcher_tier", "ResearcherTierDecision"),
    "ResearcherTierPolicy": (".researcher_tier", "ResearcherTierPolicy"),
    "ResponseCacheKeyParts": (".response_cache", "ResponseCacheKeyParts"),
    "ResponseCacheKeyPolicy": (".response_cache", "ResponseCacheKeyPolicy"),
    "RetentionDecision": (".retention", "RetentionDecision"),
    "RetentionPolicy": (".retention", "RetentionPolicy"),
    "RetentionWindows": (".retention", "RetentionWindows"),
    "LAST_RESORT_PLATFORM_TOOLS": (".retrieval", "LAST_RESORT_PLATFORM_TOOLS"),
    "RetrievalBindingDecision": (".retrieval", "RetrievalBindingDecision"),
    "RetrievalPolicy": (".retrieval", "RetrievalPolicy"),
    "SessionScratchpadPolicy": (".scratchpad", "SessionScratchpadPolicy"),
    "ShapeRecipe": (".shape", "ShapeRecipe"),
    "ShapeRecipePolicy": (".shape", "ShapeRecipePolicy"),
    "ShapeVerdict": (".shape", "ShapeVerdict"),
    "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS": (
        ".untrusted_content",
        "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS",
    ),
    "FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS": (
        ".untrusted_content",
        "FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS",
    ),
    "UntrustedContentPolicy": (".untrusted_content", "UntrustedContentPolicy"),
    "UntrustedContentResult": (".untrusted_content", "UntrustedContentResult"),
    "UntrustedContentThresholds": (".untrusted_content", "UntrustedContentThresholds"),
    "budget_untrusted_text": (".untrusted_content", "budget_untrusted_text"),
    "count_fence_blocks": (".untrusted_content", "count_fence_blocks"),
}


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = spec
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
