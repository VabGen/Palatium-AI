"""PII registry (S1): one pattern source for classification and logs.

Что здесь зафиксировано, потому что ломается молча:
  - strict-профиль ⊆ observability по общим классам: то, что считается PII при записи,
    не может исчезнуть из логов;
  - профили — подмножества ОДНОГО реестра, а не второй набор паттернов;
  - маска = сплайс найденных спанов: текст и находки не могут разойтись;
  - находка не несёт значения — её безопасно логировать.
"""

from __future__ import annotations

import pytest

from palatium_ai.core.observability.redaction import redact
from palatium_ai.core.security.pii import contains_pii, scan_pii, scrub_pii
from palatium_ai.core.security.pii.detectors import DETECTORS, detectors_for
from palatium_ai.domain.memory.pii import mask_pii_in_text, text_looks_like_pii

_EMAIL = "ivan.petrov@example.com"
_PHONE = "+375291234567"
_IBAN = "BY12ABCD1234567890"
_UNP = "123456789"
_CARD = "4111 1111 1111 1111"


def test_profiles_are_subsets_of_one_registry() -> None:
    """A class detected for storage must also be detected in logs — same table."""
    strict = {detector.kind for detector in detectors_for("strict")}
    observability = {detector.kind for detector in detectors_for("observability")}

    assert strict <= observability
    # УНП is the one log-only class: 9 bare digits are too noisy to classify a record.
    assert observability - strict == {"tax_id"}


def test_every_detector_kind_is_unique() -> None:
    kinds = [detector.kind for detector in DETECTORS]
    assert len(kinds) == len(set(kinds))


def test_both_profiles_find_the_same_email_span() -> None:
    strict = scan_pii(f"пиши {_EMAIL}", profile="strict")
    observability = scan_pii(f"пиши {_EMAIL}", profile="observability")

    assert strict.kinds == ("email",)
    assert [(f.kind, f.start, f.end) for f in strict.findings] == [(f.kind, f.start, f.end) for f in observability.findings]


def test_findings_carry_offsets_not_values() -> None:
    finding = scan_pii(_EMAIL).findings[0]

    assert set(finding.model_dump()) == {"kind", "start", "end"}
    assert _EMAIL not in finding.model_dump_json()


def test_storage_classification_sees_account_numbers() -> None:
    """R3: IBAN was log-only knowledge; a stored account number is PII too."""
    assert text_looks_like_pii(f"реквизиты {_IBAN}")
    assert contains_pii("карта " + _CARD)
    # УНП stays log-only in the strict profile.
    assert not text_looks_like_pii(f"УНП {_UNP}")


def test_luhn_gate_names_a_real_card_and_leaves_the_rest_a_plain_digit_run() -> None:
    """A non-Luhn 16-digit run is still masked, but as a phone — not mislabelled a card."""
    assert scan_pii("заказ 1234 5678 9012 3456").kinds == ("phone",)
    assert scan_pii("заказ 4111 1111 1111 1111").kinds == ("card",)


@pytest.mark.parametrize(
    "raw,bracket,angle",
    (
        (f"пиши {_EMAIL}", "пиши [EMAIL]", "пиши <email>"),
        (_PHONE, "[PHONE]", "<phone>"),
        (f"УНП {_UNP}", None, "УНП <unp>"),
        (f"IBAN {_IBAN}", "IBAN [IBAN]", "IBAN <iban_by>"),
        (_CARD, "[CARD]", "<card>"),
    ),
)
def test_mask_vocabulary_per_boundary(raw: str, bracket: str | None, angle: str) -> None:
    assert scrub_pii(raw, profile="observability", style="angle") == angle
    if bracket is not None:
        assert scrub_pii(raw, profile="strict", style="bracket") == bracket


def test_tax_id_wins_over_phone() -> None:
    """Declaration order is precedence: one span, labelled once."""
    scan = scan_pii(f"УНП {_UNP}", profile="observability")

    assert scan.kinds == ("tax_id",)
    assert len(scan.findings) == 1


def test_scrub_splices_every_finding_in_text_order() -> None:
    raw = f"{_EMAIL} и {_PHONE}, затем {_IBAN}"
    scan = scan_pii(raw, profile="strict")

    assert [f.kind for f in scan.findings] == ["email", "phone", "iban"]
    assert [f.start for f in scan.findings] == sorted(f.start for f in scan.findings)
    assert scrub_pii(raw, profile="strict") == "[EMAIL] и [PHONE], затем [IBAN]"


def test_scrub_is_idempotent() -> None:
    once = scrub_pii(f"{_EMAIL} / {_PHONE}", profile="strict")
    assert scrub_pii(once, profile="strict") == once


@pytest.mark.parametrize("raw", (_EMAIL, _PHONE, _IBAN, _CARD))
def test_boundaries_agree_on_what_is_pii(raw: str) -> None:
    """Storage masking and log redaction share the registry — no drift by construction."""
    assert text_looks_like_pii(raw)
    assert mask_pii_in_text(raw) != raw
    assert redact(raw) not in {raw, None}


def test_empty_text_is_not_scanned() -> None:
    assert scan_pii("").findings == ()
    assert scrub_pii("") == ""
    assert contains_pii("") is False
