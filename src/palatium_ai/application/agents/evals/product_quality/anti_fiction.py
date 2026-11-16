# src/palatium_ai/application/agents/evals/product_quality/anti_fiction.py

"""Anti-fiction gate: every case must fail on empty / fact-free stub (ADR-0012)."""

from __future__ import annotations

from palatium_ai.application.agents.evals.product_quality.case_schema import ProductQualityCase
from palatium_ai.application.agents.evals.product_quality.rule_checks import grade_rules

#: One suite-level stub: generic phrases without required facts. A case that
#: passes on this string is not measuring product quality.
SUITE_STUB_ANSWER = "Вот ответ на ваш вопрос. Готово. Done. OK. Всё выполнено, без деталей."


def assert_case_rejects_empty(case: ProductQualityCase) -> None:
    """Empty answer must not pass rule checks (case is not fictionally green)."""
    result = grade_rules("", case.expected)
    if result.passed:
        msg = f"case {case.id} passes on empty output — not a valid product-quality case"
        raise AssertionError(msg)


def assert_case_rejects_stub(
    case: ProductQualityCase,
    *,
    stub: str = SUITE_STUB_ANSWER,
) -> None:
    """Generic stub without required facts must fail."""
    result = grade_rules(stub, case.expected)
    if result.passed:
        msg = f"case {case.id} passes on stub {stub!r} — tighten must_contain"
        raise AssertionError(msg)


def assert_suite_anti_fiction(cases: tuple[ProductQualityCase, ...]) -> None:
    for case in cases:
        assert_case_rejects_empty(case)
        assert_case_rejects_stub(case)


__all__ = [
    "SUITE_STUB_ANSWER",
    "assert_case_rejects_empty",
    "assert_case_rejects_stub",
    "assert_suite_anti_fiction",
]
