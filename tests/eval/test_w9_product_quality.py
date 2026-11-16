# tests/eval/test_w9_product_quality.py

"""W9 product-quality evals — PR structural gates + live suites (ADR-0012)."""

from __future__ import annotations

import re

from datetime import date
from pathlib import Path

import pytest

from palatium_ai.application.agents.evals.judge_client import assert_provider_independence
from palatium_ai.application.agents.evals.product_quality.anti_fiction import (
    SUITE_STUB_ANSWER,
    assert_case_rejects_stub,
    assert_suite_anti_fiction,
)
from palatium_ai.application.agents.evals.product_quality.hashes import (
    read_adr_0012_judge_hash,
    w9_judge_prompts_sha256,
)
from palatium_ai.application.agents.evals.product_quality.loader import (
    assert_baseline_pins,
    load_cases,
    load_suite_baseline,
    refresh_policy,
    validate_baseline_pin_row,
)
from palatium_ai.application.agents.evals.product_quality.rule_checks import grade_rules
from palatium_ai.application.agents.evals.product_quality.runner import run_suite
from tests.eval.live_helpers import live_eval_enabled, require_live

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUITES = ("semantic", "context", "multi_turn", "formatter")


def test_w9_adr_0012_registry() -> None:
    adr_path = _REPO_ROOT / "docs" / "adr" / "0012-product-quality-evals.md"
    text = adr_path.read_text(encoding="utf-8")
    registry = (_REPO_ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    docs_idx = (_REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "0012" in registry
    assert "0012-product-quality-evals" in docs_idx
    assert "[baseline-refresh]" in text
    assert "w9_judge_prompts_sha256:" in text
    assert "ADR-0009" in text or "0009" in text
    assert "ADR-0010" in text or "0010" in text
    assert "ADR-0011" in text or "0011" in text
    match = re.search(r"не позже\s+\*?\*?(\d{4}-\d{2}-\d{2})\*?\*?", text)
    assert match, "ADR-0012 next-audit deadline missing"
    deadline = date.fromisoformat(match.group(1))
    assert deadline > date.today(), f"next-audit trigger {deadline} is not in the future"
    assert read_adr_0012_judge_hash() == w9_judge_prompts_sha256()


@pytest.mark.parametrize("suite", _SUITES)
def test_w9_baseline_schema_unmeasured_ok(suite: str) -> None:
    """PR-safe load; pin assert requires ≥1 measured row when present."""
    payload = load_suite_baseline(suite)  # type: ignore[arg-type]
    assert refresh_policy(suite)["marker"] == "[baseline-refresh]"  # type: ignore[arg-type]
    assert int(payload["schema_version"]) >= 1
    rows = payload.get("agents") or payload.get("request_types") or {}
    assert isinstance(rows, dict)
    assert rows
    measured = [k for k, r in rows.items() if isinstance(r, dict) and r.get("measured") is True]
    if measured:
        assert_baseline_pins(suite)  # type: ignore[arg-type]
    else:
        with pytest.raises(ValueError, match="measured:true required"):
            assert_baseline_pins(suite)  # type: ignore[arg-type]


def test_w9_baseline_rejects_placeholder() -> None:
    """0.0 and null-under-measured:true must not sneak into a merge pin."""
    with pytest.raises(ValueError, match="0\\.0 is not a valid unmeasured placeholder"):
        validate_baseline_pin_row(
            "semantic",
            "researcher",
            {"actual_pass_rate": 0.0, "min_pass_rate": 0.0, "measured": False},
        )
    with pytest.raises(ValueError, match="rejects null"):
        validate_baseline_pin_row(
            "semantic",
            "researcher",
            {"actual_pass_rate": None, "min_pass_rate": None, "measured": True},
        )
    validate_baseline_pin_row(
        "semantic",
        "researcher",
        {"actual_pass_rate": None, "min_pass_rate": None, "measured": False},
    )
    validate_baseline_pin_row(
        "semantic",
        "researcher",
        {"actual_pass_rate": 0.75, "min_pass_rate": 0.75, "measured": True},
    )


def test_w9_judge_provider_independence() -> None:
    assert_provider_independence(judge_provider="anthropic", generator_provider="openai")
    with pytest.raises(ValueError, match="must differ"):
        assert_provider_independence(judge_provider="openai", generator_provider="openai")


@pytest.mark.parametrize("suite", _SUITES)
def test_w9_anti_fiction(suite: str) -> None:
    cases = load_cases(suite)  # type: ignore[arg-type]
    assert cases
    assert_suite_anti_fiction(cases)
    assert "готово" in SUITE_STUB_ANSWER.casefold() or "done" in SUITE_STUB_ANSWER.casefold()
    for case in cases:
        assert_case_rejects_stub(case, stub=SUITE_STUB_ANSWER)


def test_w9_semantic_case_count_floor() -> None:
    cases = load_cases("semantic")
    by_agent: dict[str, int] = {}
    for case in cases:
        by_agent[case.agent] = by_agent.get(case.agent, 0) + 1
    for agent in ("researcher", "analyst", "coder", "formatter"):
        assert by_agent.get(agent, 0) >= 10, f"{agent} needs ≥10 semantic cases"


def test_w9_context_has_present_and_absent() -> None:
    cases = load_cases("context")
    tags = {t for c in cases for t in c.tags}
    assert "present" in tags
    assert "absent" in tags


def test_w9_multi_turn_three_scenarios() -> None:
    cases = load_cases("multi_turn")
    ids = {c.id for c in cases}
    assert "mt-researcher-reference-01" in ids
    assert "mt-researcher-compact-01" in ids
    assert "mt-researcher-correction-01" in ids
    baseline = load_suite_baseline("multi_turn")
    assert int(baseline["max_turns"]) >= 5


def test_w9_formatter_request_types() -> None:
    cases = load_cases("formatter")
    types = {str(c.input.get("request_type") or c.scenario) for c in cases}
    for needed in ("list", "comparison", "instruction", "explanation", "code", "field_preservation"):
        assert needed in types


def test_w9_rule_checks_unit() -> None:
    ok = grade_rules(
        "ORION-7 owns проект Зенит",
        {"must_contain": ["ORION-7", "Зенит"], "must_not_contain": ["ACME"]},
    )
    assert ok.passed
    bad = grade_rules("hello", {"must_contain": ["ORION-7"], "must_not_contain": []})
    assert not bad.passed


@pytest.mark.asyncio()
async def test_w9_supplied_answer_path() -> None:
    """Rule path works without live LLM when answers are supplied (PR-safe)."""
    cases = load_cases("semantic")
    sample = next(c for c in cases if c.agent == "researcher" and not c.needs_judge)
    needles = sample.expected.get("must_contain") or []
    answer = " ".join(str(n) for n in needles)
    report = await run_suite(
        "semantic",
        supplied_answers={sample.id: answer},
        case_ids={sample.id},
    )
    assert report.outcomes[0].passed


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_semantic_correctness() -> None:
    assert live_eval_enabled()
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    settings = get_settings()
    llm = create_llm_client(settings)
    report = await run_suite("semantic", llm=llm)
    report.assert_baselines()


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_context_utilization() -> None:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    llm = create_llm_client(get_settings())
    report = await run_suite("context", llm=llm)
    report.assert_baselines()


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_multi_turn_coherence_reference() -> None:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    llm = create_llm_client(get_settings())
    report = await run_suite("multi_turn", llm=llm, case_ids={"mt-researcher-reference-01"})
    assert report.outcomes
    report.assert_baselines()


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_multi_turn_coherence_compact() -> None:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    llm = create_llm_client(get_settings())
    report = await run_suite("multi_turn", llm=llm, case_ids={"mt-researcher-compact-01"})
    assert report.outcomes
    report.assert_baselines()


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_multi_turn_coherence_correction() -> None:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    llm = create_llm_client(get_settings())
    report = await run_suite("multi_turn", llm=llm, case_ids={"mt-researcher-correction-01"})
    assert report.outcomes
    report.assert_baselines()


@require_live
@pytest.mark.live()
@pytest.mark.asyncio()
async def test_w9_formatter_quality() -> None:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.llm.factory import create_llm_client

    llm = create_llm_client(get_settings())
    report = await run_suite("formatter", llm=llm)
    report.assert_baselines()
