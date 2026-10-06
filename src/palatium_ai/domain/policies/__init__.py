# src/palatium_ai/domain/policies/__init__.py

"""Доменные политики и оси (055).

Eager: только types. Политики (ContinuityPolicy и др.) — lazy через __getattr__,
иначе mcp.models → policies → continuity → agents → mcp.models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import (
    LOW_RISK_ROUTE_STRATEGIES,
    AgentRole,
    ContinuationKind,
    ExecutionStrategy,
    ModelTier,
    RouteStrategy,
    TaskKind,
    UnderspecificationKind,
    UntrustedContentAction,
)

if TYPE_CHECKING:
    from .compact import CompactPolicy
    from .contextualizer import ContextualizerGateDecision, ContextualizerPolicy
    from .continuity import ContinuityPolicy, EffectiveRoutingIntent
    from .critic import CriticGateDecision, CriticPolicy
    from .locale import ReplyLocalePolicy
    from .memory_namespace import MemoryNamespaceBinding, MemoryNamespacePolicy
    from .promotion import PromotionPolicy
    from .retrieval import LAST_RESORT_PLATFORM_TOOLS, RetrievalBindingDecision, RetrievalPolicy
    from .scratchpad import SessionScratchpadPolicy
    from .untrusted_content import (
        DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
        UntrustedContentPolicy,
        UntrustedContentResult,
        UntrustedContentThresholds,
        budget_untrusted_text,
    )

__all__ = [
    "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS",
    "LAST_RESORT_PLATFORM_TOOLS",
    "LOW_RISK_ROUTE_STRATEGIES",
    "AgentRole",
    "CompactPolicy",
    "ContextualizerGateDecision",
    "ContextualizerPolicy",
    "ContinuationKind",
    "ContinuityPolicy",
    "CriticGateDecision",
    "CriticPolicy",
    "EffectiveRoutingIntent",
    "ExecutionStrategy",
    "MemoryNamespaceBinding",
    "MemoryNamespacePolicy",
    "ModelTier",
    "PromotionPolicy",
    "ReplyLocalePolicy",
    "RetrievalBindingDecision",
    "RetrievalPolicy",
    "RouteStrategy",
    "SessionScratchpadPolicy",
    "TaskKind",
    "UnderspecificationKind",
    "UntrustedContentAction",
    "UntrustedContentPolicy",
    "UntrustedContentResult",
    "UntrustedContentThresholds",
    "budget_untrusted_text",
]

_LAZY: dict[str, tuple[str, str]] = {
    "CompactPolicy": (".compact", "CompactPolicy"),
    "ContinuityPolicy": (".continuity", "ContinuityPolicy"),
    "EffectiveRoutingIntent": (".continuity", "EffectiveRoutingIntent"),
    "ContextualizerGateDecision": (".contextualizer", "ContextualizerGateDecision"),
    "ContextualizerPolicy": (".contextualizer", "ContextualizerPolicy"),
    "CriticGateDecision": (".critic", "CriticGateDecision"),
    "CriticPolicy": (".critic", "CriticPolicy"),
    "MemoryNamespaceBinding": (".memory_namespace", "MemoryNamespaceBinding"),
    "MemoryNamespacePolicy": (".memory_namespace", "MemoryNamespacePolicy"),
    "PromotionPolicy": (".promotion", "PromotionPolicy"),
    "ReplyLocalePolicy": (".locale", "ReplyLocalePolicy"),
    "LAST_RESORT_PLATFORM_TOOLS": (".retrieval", "LAST_RESORT_PLATFORM_TOOLS"),
    "RetrievalBindingDecision": (".retrieval", "RetrievalBindingDecision"),
    "RetrievalPolicy": (".retrieval", "RetrievalPolicy"),
    "SessionScratchpadPolicy": (".scratchpad", "SessionScratchpadPolicy"),
    "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS": (
        ".untrusted_content",
        "DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS",
    ),
    "UntrustedContentPolicy": (".untrusted_content", "UntrustedContentPolicy"),
    "UntrustedContentResult": (".untrusted_content", "UntrustedContentResult"),
    "UntrustedContentThresholds": (".untrusted_content", "UntrustedContentThresholds"),
    "budget_untrusted_text": (".untrusted_content", "budget_untrusted_text"),
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
