"""FormatterMemoryMergePolicy — keep identity hints with worker source (SB3)."""

from __future__ import annotations

from palatium_ai.domain.policies.formatter_memory_merge import FormatterMemoryMergePolicy


def test_full_hints_without_source() -> None:
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("меня зовут Геннадий", "предпочитает краткие ответы"),
        has_source_content=False,
    )
    assert len(decision.hints) == 2
    assert decision.reason == "full_hints_no_source"


def test_identity_slice_with_source() -> None:
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("меня зовут Геннадий", "длинный факт о рынке"),
        has_source_content=True,
    )
    assert decision.hints == ("меня зовут Геннадий", "длинный факт о рынке")[:2]
    assert "with_source" in decision.reason


def test_preference_kinds_preferred() -> None:
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("fact dump", "user prefers RU"),
        has_source_content=True,
        hit_kinds=("fact", "preference"),
    )
    assert decision.hints == ("user prefers RU",)


def test_known_kinds_without_preference_inject_nothing() -> None:
    """Facts/pins are not personalisation: «сравни файлы» must not enter the composer."""
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("привет я геннадий а ты", "сравни файлы"),
        has_source_content=True,
        hit_kinds=("fact", "fact"),
    )
    assert decision.hints == ()
    assert decision.reason == "no_personalization_kinds_with_source"


def test_content_transform_never_injects_hints() -> None:
    """A rewrite of the prior answer must not be steered by remembered topics."""
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("сравни файлы",),
        has_source_content=True,
        hit_kinds=("fact",),
        content_transform=True,
    )
    assert decision.hints == ()
    assert decision.reason == "content_transform_no_personalization"
