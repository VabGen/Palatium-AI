"""GroundingPolicy — empty retrieval actions + clarification copy."""

from palatium_ai.domain.policies.grounding import GroundingPolicy


def test_coerce_defaults_to_optional() -> None:
    assert GroundingPolicy.coerce_mode(None) == "optional"
    assert GroundingPolicy.coerce_mode("bogus") == "optional"
    assert GroundingPolicy.coerce_mode("required") == "required"


def test_empty_flag_off_stubs() -> None:
    d = GroundingPolicy.decide_empty_retrieval(enabled=False, grounding="optional")
    assert d.action == "stub"


def test_empty_optional_degrades() -> None:
    d = GroundingPolicy.decide_empty_retrieval(enabled=True, grounding="optional")
    assert d.action == "degrade_reason"


def test_empty_required_clarifies() -> None:
    d = GroundingPolicy.decide_empty_retrieval(enabled=True, grounding="required")
    assert d.action == "clarify"


def test_required_blocks_prior_skip_when_adaptive_on() -> None:
    assert GroundingPolicy.allows_prior_grounded_skip(enabled=True, grounding="required") is False
    assert GroundingPolicy.allows_prior_grounded_skip(enabled=True, grounding="optional") is True
    assert GroundingPolicy.allows_prior_grounded_skip(enabled=False, grounding="required") is True


def test_required_blocks_sticky_rehydrate_when_adaptive_on() -> None:
    assert GroundingPolicy.allows_sticky_attachment_rehydrate(enabled=True, grounding="required") is False
    assert GroundingPolicy.allows_sticky_attachment_rehydrate(enabled=True, grounding="optional") is True
    assert GroundingPolicy.allows_sticky_attachment_rehydrate(enabled=False, grounding="required") is True


def test_clarification_embeds_file_query() -> None:
    text = GroundingPolicy.required_empty_clarification("что в моём загруженном файле отчёт.docx?")
    assert "отчёт.docx" in text or "файле" in text
    assert "По запросу" in text
    assert "приложите файл" in text.lower() or "источник" in text.lower()


def test_clarification_embeds_sales_query_snippet() -> None:
    ask = "Сравни подписку на облачный сервис и покупку коробочного ПО"
    text = GroundingPolicy.required_empty_clarification(ask)
    assert "облачный" in text or "короб" in text
    assert "ничего не найдено" in text.lower()
    assert text != GroundingPolicy.required_empty_clarification(None)
