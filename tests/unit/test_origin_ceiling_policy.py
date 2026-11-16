# tests/unit/test_origin_ceiling_policy.py

"""ADR 0008 OriginCeilingPolicy + resolve helpers (CMD1)."""

from __future__ import annotations

from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.memory.types import (
    MEMORY_EXPLICIT_WRITE_KEY,
    resolve_memory_origin,
    resolve_memory_trust,
)
from palatium_ai.domain.policies.origin_ceiling import INFERRED_SCORE_FACTOR, OriginCeilingPolicy
from palatium_ai.domain.policies.promotion import PromotionPolicy


def test_resolve_legacy_and_explicit() -> None:
    assert resolve_memory_origin({}) == "legacy"
    assert resolve_memory_trust({}) == "inferred"
    explicit = {MEMORY_EXPLICIT_WRITE_KEY: True}
    assert resolve_memory_origin(explicit) == "user_hitl"
    assert resolve_memory_trust(explicit) == "verified"
    extract = {"source_task_id": "extract-1", "origin": "extract", "trust": "inferred"}
    assert resolve_memory_origin(extract) == "extract"
    assert resolve_memory_trust(extract) == "inferred"


def test_recall_gates() -> None:
    assert OriginCeilingPolicy.allow_in_recall("verified") is True
    assert OriginCeilingPolicy.allow_in_recall("inferred") is True
    assert OriginCeilingPolicy.allow_in_recall("quarantined") is False
    assert OriginCeilingPolicy.adjust_score(10.0, "inferred") == 10.0 * INFERRED_SCORE_FACTOR
    assert OriginCeilingPolicy.adjust_score(10.0, "verified") == 10.0


def test_promote_inferred_needs_access_and_blocks_pii() -> None:
    assert (
        OriginCeilingPolicy.allow_promote(
            "inferred",
            access_frequency=3,
            min_access_frequency=3,
            contains_pii=False,
        )
        is True
    )
    assert (
        OriginCeilingPolicy.allow_promote(
            "inferred",
            access_frequency=2,
            min_access_frequency=3,
            contains_pii=False,
        )
        is False
    )
    assert (
        OriginCeilingPolicy.allow_promote(
            "inferred",
            access_frequency=9,
            min_access_frequency=3,
            contains_pii=True,
        )
        is False
    )
    assert (
        OriginCeilingPolicy.allow_promote(
            "verified",
            access_frequency=0,
            min_access_frequency=3,
            contains_pii=True,
        )
        is True
    )


def test_promotion_policy_blocks_inferred_pii() -> None:
    thresholds = PromotionThresholds(min_access_frequency=3, min_importance=0.5)
    candidate = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="pii",
        text="passport 123",
        kind="fact",
        importance=0.9,
        access_frequency=9,
        user_id="u1",
        confidence=0.9,
        contains_pii=True,
        trust="inferred",
    )
    assert PromotionPolicy.should_promote(candidate, thresholds=thresholds) is False
    verified = candidate.model_copy(update={"trust": "verified"})
    assert PromotionPolicy.should_promote(verified, thresholds=thresholds) is True
