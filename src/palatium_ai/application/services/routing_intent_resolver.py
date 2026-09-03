# src/palatium_ai/application/services/routing_intent_resolver.py

"""Apply ContinuityPolicy after intent classification (context_enricher axis)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.policies import ContinuityPolicy, EffectiveRoutingIntent

if TYPE_CHECKING:
    from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
    from palatium_ai.domain.memory.turns import DialogTurnWindow


def resolve_routing_intent(
    *,
    contextualizer: ContextualizerOutput | None,
    dialog: DialogTurnWindow | None,
    raw_intent: IntentClassifierOutput | None,
) -> EffectiveRoutingIntent:
    """Single entry for continuity remap after IntentClassifier."""
    return ContinuityPolicy.resolve(
        contextualizer=contextualizer,
        dialog=dialog,
        raw_intent=raw_intent,
    )
