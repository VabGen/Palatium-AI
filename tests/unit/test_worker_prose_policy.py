"""WorkerProsePolicy — never ship JSON envelopes as user-visible answers."""

from __future__ import annotations

import json

from palatium_ai.application.agents.researcher.parsing import parse_researcher_output
from palatium_ai.domain.policies.worker_prose import WorkerProsePolicy


def test_lift_summary_from_valid_envelope() -> None:
    body = "## Продолжение\n\nЖил-был муж и жена."
    raw = json.dumps({"summary": body, "confidence": 0.9, "sources_used": []}, ensure_ascii=False)
    assert WorkerProsePolicy.lift_summary_envelope(raw) == body
    assert WorkerProsePolicy.user_visible(raw) == body


def test_lift_summary_from_broken_envelope_with_raw_newlines() -> None:
    """Codec often fails when the model puts raw newlines inside the summary string."""
    # Deliberately invalid JSON: unescaped newline inside the string value.
    raw = '{\n  "summary": "## Продолжение\n\nЖил-был муж и жена.",\n  "confidence": 0.9\n}'
    lifted = WorkerProsePolicy.lift_summary_envelope(raw)
    assert lifted is not None
    assert lifted.startswith("## Продолжение")
    assert "{" not in lifted
    assert '"summary"' not in lifted


def test_lift_summary_after_disclaimer_prefix() -> None:
    body = "Текст продолжения сказки."
    envelope = json.dumps({"summary": body, "confidence": 0.8, "sources_used": []}, ensure_ascii=False)
    prefixed = "Ответ без подтверждения во внешних источниках.\n\n" + envelope
    assert WorkerProsePolicy.user_visible(prefixed) == body


def test_ordinary_prose_unchanged() -> None:
    prose = "1. Краткий пересказ: компания подписала соглашение."
    assert WorkerProsePolicy.user_visible(prose) == prose
    assert WorkerProsePolicy.lift_summary_envelope(prose) is None


def test_parse_researcher_recovers_broken_envelope_instead_of_freeform_bleed() -> None:
    """Regression: freeform fallback must not paint the wire JSON (live 2026-11-16)."""
    story = "## Продолжение\n\nЖил-был муж и жена. Муж пошёл в магазин и вернулся с жизнью."
    # Broken outer object — field extractor must still lift summary.
    raw = '{"summary": "' + story.replace("\n", "\\n") + '", "confidence": 0.91, "sources_used": []'
    # Missing closing `}` → codec fails; extractor recovers.
    parsed = parse_researcher_output(raw)
    assert parsed.summary.startswith("## Продолжение")
    assert '"summary"' not in parsed.summary
    assert parsed.summary.startswith("{") is False
    assert "envelope_recovered" in parsed.sources_used or parsed.confidence >= 0.7


def test_parse_researcher_valid_envelope_still_works() -> None:
    body = "Полный ответ пользователю."
    raw = json.dumps({"summary": body, "confidence": 0.95, "sources_used": ["llm"]}, ensure_ascii=False)
    parsed = parse_researcher_output(raw)
    assert parsed.summary == body
    assert parsed.confidence == 0.95
