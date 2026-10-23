# tests/eval/test_m9_flag_gates.py

"""M9 gate table: a flag is ON only while its eval is green (M9 §5–§6).

The design (`docs/plans/m9-eval-design.md`) promises that every M8 switch has a metric,
a threshold and a rollback, and that "enabled because the code exists" is not a reason.
This module is the executable half of that promise: it re-derives the numbers through the
real promote service (not a helper in isolation) and pins every flag that is still blocked,
so turning one on is a deliberate edit here with evidence, never an env default drifting.

Steps 1–2 (metrics + baseline) live in ``test_m9_eval_metrics.py``,
``test_memory_extract_dedup.py`` and ``tests/perf/test_memory_query_latency.py``. This
file covers step 3 and the blockers that keep steps 4–7 out until their precondition is
implemented.
"""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.core.config.memory import MemoryConfig
from palatium_ai.domain.memory.duplicates import duplicate_rate, normalize_memory_text
from palatium_ai.domain.memory.promotion import PromotionThresholds
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort

#: Same "raw extract" corpus as ``test_memory_extract_dedup.py``: one baseline for both the
#: extract-side and the batch-side metric, so the two levers are compared on equal footing.
PROMOTION_CORPUS: tuple[str, ...] = (
    "User prefers the weekly status update in Confluence over the daily standup call",
    "User prefers the weekly status update in Confluence over the daily standup meeting",
    "user prefers the weekly status update in confluence over the daily standup call",
    "User prefers meeting agendas as tables.",
    "User prefers meeting agendas as tables.",
    "Предпочитает повестки встреч в виде таблиц.",
    "Созвон с Acme перенесён на 14:00.",
    "Созвон с Acme перенесён на 15:00.",
)

#: Gate used by §5.5: duplicate rate must fall by at least half, Recall@4 may not drop.
_MIN_DUPLICATE_REDUCTION = 0.5

#: Thresholds that let every corpus line through, so the measurement is about decoupling
#: and not about the promotion policy (which has its own tests).
_THRESHOLDS = PromotionThresholds(min_access_frequency=3, min_importance=0.4)

_OWNER = "m9-gate"
_NAMESPACE = ("user", _OWNER)

#: Flags that must stay OFF until their precondition exists (§5.3–5.7, §6 steps 4–7).
#: Flipping any of them requires closing the listed blocker and adding its measured gate
#: to this module — which is exactly the point of the table.
BLOCKED_FLAGS: dict[str, str] = {
    "embedding_rerank": "§5.2 p95 ratio (≤ x1.5) is not measured against the live embedding gateway",
    "cross_encoder_rerank": "§5.3 production port is TokenOverlapCrossEncoder, not a real cross-encoder",
    "bayesian_trust": "§5.6 observe_failure is never called on supersede, so confidence only rises",
}

#: Knobs removed 2026-10-20 (§9.2): they had no observable effect, and rule 050 forbids
#: keeping an unused switch. The domain helpers stay for the wave that gives them a
#: consumer; re-introducing a flag means writing its gate in this module first.
PRUNED_FLAGS: tuple[str, ...] = ("binary_quantize_rerank", "hebbian_edge_bump")


async def _promote_corpus(*, decouple: bool) -> list[str]:
    """Run the real batch service over the corpus and return the promoted fact texts."""
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    for index, text in enumerate(PROMOTION_CORPUS):
        entry_key = f"m9-{index}"
        await memory.put(
            namespace=_NAMESPACE,
            key=entry_key,
            value={"text": text, "kind": "fact", "confidence": 0.9, "importance": 0.8},
        )
        for _ in range(3):
            await memory.bump_access(namespace=_NAMESPACE, key=entry_key)
    service = MemoryPromotionService(
        memory=memory,
        graph_write=graph,
        thresholds=_THRESHOLDS,
        xmemory_decouple=decouple,
    )
    await service.run_batch(user_id=_OWNER, limit=32)
    facts = await graph.list_active_facts(user_id=_OWNER, limit=32)
    return [fact.text for fact in facts]


@pytest.mark.asyncio()
async def test_gate_xmemory_decouple_clears_the_duplicate_rate_without_losing_a_fact() -> None:
    """§5.5: duplicate rate drops by half (measured 0.25 -> 0.0), distinct facts unchanged.

    The distinct-fact set is the Recall proxy that matters here: collapsing verbatim repeats
    must not delete information. Paraphrase and translation survive (that is the E5 prompt's
    job), so the on-state is not "deduplicated", only "no longer verbatim-duplicated".
    """
    without = await _promote_corpus(decouple=False)
    with_decouple = await _promote_corpus(decouple=True)

    baseline = duplicate_rate(without)
    gated = duplicate_rate(with_decouple)
    assert baseline == pytest.approx(0.25), "corpus/baseline drift: update M9 §6 step 2 first"
    assert gated <= baseline * _MIN_DUPLICATE_REDUCTION
    assert gated == 0.0

    # No information lost: the same set of normalized facts reaches the graph.
    assert {normalize_memory_text(text) for text in with_decouple} == {normalize_memory_text(text) for text in without}
    assert len(with_decouple) < len(without), "the gate must observe the collapse, not just pass"


def _declared_default(flag: str) -> object:
    """Field default from the model, not ``MemoryConfig()`` — env files must not fake a gate.

    Reading the instantiated config would let a developer's local ``.env`` (or CI env) make
    a blocked flag look enabled, which is exactly the drift this table exists to catch.
    """
    return MemoryConfig.model_fields[flag].default


def test_gate_xmemory_decouple_default_follows_the_green_gate() -> None:
    """Step 3 decision: this flag is ON because its numbers are above, not by preference."""
    assert _declared_default("xmemory_decouple") is True


@pytest.mark.parametrize("flag,blocker", sorted(BLOCKED_FLAGS.items()))
def test_gate_blocked_flags_stay_off(flag: str, blocker: str) -> None:
    """A blocked flag defaults OFF; the reason names the missing precondition, not a mood."""
    assert blocker.startswith("§5."), "blocker must cite the design section it comes from"
    assert _declared_default(flag) is False, (
        f"{flag} was enabled without closing its gate: {blocker} "
        "(add the measured gate to this module before flipping the default)"
    )


def test_half_life_is_a_value_not_a_switch() -> None:
    """§3: τ-decay is always active; ``7.0`` is a tunable value, never "OFF"."""
    assert _declared_default("importance_half_life_days") == 7.0


@pytest.mark.parametrize("flag", PRUNED_FLAGS)
def test_gate_pruned_knobs_stay_removed(flag: str) -> None:
    """§9.2: a knob with no observable effect is removed, not parked at ``false``."""
    assert flag not in MemoryConfig.model_fields, (
        f"{flag} was re-introduced without a gate: give it a metric/threshold in "
        "m9-eval-design.md §5 and move it to BLOCKED_FLAGS or an enabled gate first"
    )
