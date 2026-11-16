"""DialogCorrectionPolicy — W10 P1.1 correction leak (no phrase-list hardcoding)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.dialog_correction import DialogCorrectionPolicy


def _turn(role: str, content: str, *, seq: int) -> DialogTurn:
    return DialogTurn(
        id=uuid4(),
        thread_id="t-corr",
        role=role,  # type: ignore[arg-type]
        content=content,
        seq=seq,
        created_at=datetime.now(UTC),
    )


def test_orion_vega_correction_strips_old_client() -> None:
    """Live W10 2b: corrected client must not co-exist with the retracted name."""
    turns = (
        _turn("user", "Клиент — ORION-7", seq=0),
        _turn("assistant", "Записал: основной клиент ORION-7.", seq=1),
        _turn("user", "Стоп, ошибся, клиент — VEGA-9", seq=2),
        _turn("assistant", "Принято, клиент VEGA-9.", seq=3),
        _turn("user", "Какой клиент у нас основной?", seq=4),
    )
    redacted = DialogCorrectionPolicy.redact_superseded(turns)
    texts = [turn.content for turn in redacted]
    assert all("ORION-7" not in text for text in texts)
    assert any("VEGA-9" in text for text in texts)
    assert texts[-1].endswith("?")


def test_iris_login_correction_for_eval_scenario() -> None:
    turns = (
        _turn("user", "Владелец аккаунта — login iris.old.", seq=0),
        _turn("user", "Подтверди, пожалуйста.", seq=1),
        _turn("user", "Исправление: правильный login — iris.new, не iris.old.", seq=2),
        _turn("user", "Ок.", seq=3),
        _turn("user", "Какой login владельца сейчас?", seq=4),
    )
    window = DialogTurnWindow(thread_id="t", turns=turns, limit=12)
    block = DialogCorrectionPolicy.apply(window).as_prompt_block()
    # Old login must leave the prompt window; negation in the correcting turn may
    # still mention it — the retracted *assertion* turn is what we drop.
    assert "Владелец аккаунта — login iris.old." not in block
    assert "iris.new" in block


def test_questions_do_not_supersede_assertions() -> None:
    turns = (
        _turn("user", "Клиент — VEGA-9", seq=0),
        _turn("user", "Какой клиент у нас основной?", seq=1),
    )
    redacted = DialogCorrectionPolicy.redact_superseded(turns)
    assert len(redacted) == 2
    assert redacted[0].content == "Клиент — VEGA-9"


def test_unrelated_topics_stay() -> None:
    turns = (
        _turn("user", "Люблю кофе", seq=0),
        _turn("user", "Клиент — VEGA-9", seq=1),
    )
    assert DialogCorrectionPolicy.redact_superseded(turns) == turns


def test_as_prompt_block_applies_correction() -> None:
    window = DialogTurnWindow(
        thread_id="t",
        turns=(
            _turn("user", "Клиент — ORION-7", seq=0),
            _turn("user", "Клиент — VEGA-9", seq=1),
        ),
        limit=12,
    )
    block = window.as_prompt_block()
    assert "ORION-7" not in block
    assert "VEGA-9" in block


def test_filter_superseded_texts_drops_scratchpad_orion() -> None:
    turns = (
        _turn("user", "Клиент — ORION-7", seq=0),
        _turn("user", "Стоп, ошибся, клиент — VEGA-9", seq=1),
    )
    kept = DialogCorrectionPolicy.filter_superseded_texts(
        ("Клиент — ORION-7", "Стоп, ошибся, клиент — VEGA-9", "BGT-42 ритм"),
        turns,
    )
    assert all("ORION-7" not in text for text in kept)
    assert any("VEGA-9" in text for text in kept)
    assert any("BGT-42" in text for text in kept)


def test_as_prompt_block_does_not_repin_superseded_scratchpad() -> None:
    """Live W10 2b: after redact, pinned ORION must not re-enter dialog_history."""
    window = DialogTurnWindow(
        thread_id="t",
        turns=(
            _turn("user", "Клиент — ORION-7", seq=0),
            _turn("user", "Стоп, ошибся, клиент — VEGA-9", seq=1),
            _turn("assistant", "Принято. Основной клиент — VEGA-9.", seq=2),
        ),
        limit=12,
    )
    block = window.as_prompt_block(pinned_user_texts=("Клиент — ORION-7", "Клиент — VEGA-9"))
    assert "ORION-7" not in block
    assert "VEGA-9" in block
    assert "dialog_policy" in block
