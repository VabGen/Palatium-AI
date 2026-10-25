"""Write-time PII gate: one classification, one metric (020, 040).

Метрика считается по классам, а не по булеву флагу: `contains_pii=true` оператору
не говорит, что именно пишется в память. Значение спана в метку не попадает никогда —
иначе метрика сама становится утечкой.
"""

from __future__ import annotations

from palatium_ai.application.services.pii_gate import classify_for_write
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.memory.pii import classify_pii


def test_gate_counts_the_detected_class() -> None:
    before = agent_metrics.pii_detection_count("email", "strict")

    assert classify_for_write(text="пиши на ivan.petrov@example.com") is True

    assert agent_metrics.pii_detection_count("email", "strict") == before + 1


def test_gate_counts_account_numbers_as_iban() -> None:
    before = agent_metrics.pii_detection_count("iban", "strict")

    assert classify_for_write(text="счёт BY12ABCD1234567890") is True

    assert agent_metrics.pii_detection_count("iban", "strict") == before + 1


def test_clean_text_is_not_counted() -> None:
    before = sum(agent_metrics.pii_detection_count(kind, "strict") for kind in ("email", "phone", "iban", "card", "passport"))

    assert classify_for_write(text="обычная заметка без контактов") is False

    after = sum(agent_metrics.pii_detection_count(kind, "strict") for kind in ("email", "phone", "iban", "card", "passport"))
    assert after == before


def test_client_flag_escalates_but_never_de_escalates() -> None:
    escalated = classify_pii(text="обычная заметка", client_flag=True)
    assert escalated.contains is True
    assert escalated.kinds == ()

    downgraded = classify_pii(text="ivan.petrov@example.com", client_flag=False)
    assert downgraded.contains is True


def test_metric_labels_stay_within_the_closed_kind_set() -> None:
    """Scan.kinds is the only source of labels — no free-form text can reach a metric."""
    scan = classify_pii(text="ivan.petrov@example.com +375291234567")
    assert set(scan.kinds) <= {"email", "phone", "iban", "tax_id", "card", "passport"}
