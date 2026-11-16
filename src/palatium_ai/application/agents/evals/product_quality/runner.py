# src/palatium_ai/application/agents/evals/product_quality/runner.py

"""Run W9 suites: live generate → rule gate → optional judge → pass_rate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from palatium_ai.application.agents.evals.judge_client import EvalJudgeClientFactory
from palatium_ai.application.agents.evals.product_quality.case_schema import (
    ProductQualityCase,
    W9Suite,
)
from palatium_ai.application.agents.evals.product_quality.generator import (
    dialog_transcript,
    generate_answer,
)
from palatium_ai.application.agents.evals.product_quality.judge import grade_with_judge
from palatium_ai.application.agents.evals.product_quality.loader import (
    load_cases,
    load_suite_baseline,
    min_pass_rate,
)
from palatium_ai.application.agents.evals.product_quality.rule_checks import grade_rules
from palatium_ai.domain.agents.evals import GradeResult
from palatium_ai.domain.ports.llm import LLMPort


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    agent: str
    passed: bool
    details: str
    score: float
    answer: str = ""
    rule_passed: bool = False
    judge_passed: bool | None = None


@dataclass(frozen=True)
class SuiteReport:
    suite: W9Suite
    outcomes: tuple[CaseOutcome, ...]
    pass_rate_by_key: Mapping[str, float]

    def assert_baselines(self) -> None:
        """Compare live pass_rate to measured floors. Skips when baseline is unmeasured."""
        payload = load_suite_baseline(self.suite)
        rows = payload.get("agents") or payload.get("request_types") or {}
        if not isinstance(rows, dict):
            return
        unmeasured = [
            key for key in self.pass_rate_by_key if isinstance(rows.get(key), dict) and rows[key].get("measured") is not True
        ]
        if unmeasured:
            msg = (
                f"{self.suite}: baseline not measured yet for {unmeasured} — "
                "skip floor assert (run Phase 3 then pin with measured:true)"
            )
            raise AssertionError(msg)
        for key, rate in self.pass_rate_by_key.items():
            floor = min_pass_rate(self.suite, key=key)
            if rate + 1e-9 < floor:
                msg = f"{self.suite}/{key}: pass_rate {rate:.3f} < min_pass_rate {floor:.3f}"
                raise AssertionError(msg)


def _group_key(case: ProductQualityCase) -> str:
    if case.suite == "formatter":
        return str(case.input.get("request_type") or case.scenario)
    return case.agent


def _turn_case(case: ProductQualityCase, user_text: str) -> ProductQualityCase:
    return ProductQualityCase(
        id=case.id,
        suite=case.suite,
        agent=case.agent,
        scenario=case.scenario,
        input={"user_text": user_text},
        context=case.context,
        expected=case.expected,
        grader=case.grader,
        needs_judge=case.needs_judge,
        tags=case.tags,
        turns=(),
    )


def _compact_transcript(history: list[dict[str, Any]], retain: list[Any]) -> str:
    lines = dialog_transcript(history).splitlines()
    kept = [line for line in lines if any(str(tok).casefold() in line.casefold() for tok in retain)]
    return "\n".join(kept) if kept else dialog_transcript(history)


async def _generate_multi_turn(
    case: ProductQualityCase,
    *,
    llm: LLMPort,
    supplied: str | None,
) -> str:
    if supplied is not None:
        return supplied
    history: list[dict[str, Any]] = []
    answer = ""
    user_turns = [t for t in case.turns if str(t.get("role") or "user") == "user"]
    for idx, turn in enumerate(user_turns):
        content = str(turn.get("content") or "")
        is_last = idx == len(user_turns) - 1
        extra = dialog_transcript(history)
        if is_last and case.context.get("compact_before_final"):
            retain = case.expected.get("must_contain") or []
            extra = _compact_transcript(history, list(retain) if isinstance(retain, list) else [])
        answer = await generate_answer(
            _turn_case(case, content),
            llm=llm,
            extra_dialog=extra,
        )
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": answer})
    return answer


async def _run_one(
    case: ProductQualityCase,
    *,
    llm: LLMPort | None,
    supplied_answers: Mapping[str, str] | None,
    llm_factory: EvalJudgeClientFactory | None,
) -> CaseOutcome:
    supplied = None if supplied_answers is None else supplied_answers.get(case.id)
    if llm is None and supplied is None:
        return CaseOutcome(
            case_id=case.id,
            agent=case.agent,
            passed=False,
            details="live LLM required (set PALATIUM_LIVE_EVAL=1) or supply answers",
            score=0.0,
        )

    if case.suite == "multi_turn" and case.turns:
        answer = await _generate_multi_turn(case, llm=llm, supplied=supplied)  # type: ignore[arg-type]
    else:
        answer = await generate_answer(case, llm=llm, supplied_answer=supplied)  # type: ignore[arg-type]

    rules = grade_rules(answer, case.expected)
    if not rules.passed:
        return CaseOutcome(
            case_id=case.id,
            agent=case.agent,
            passed=False,
            details=rules.details,
            score=rules.score,
            answer=answer,
            rule_passed=False,
            judge_passed=None,
        )
    final: GradeResult = rules
    judge_passed: bool | None = None
    if case.needs_judge or case.grader == "rule_then_judge":
        final = await grade_with_judge(case, answer, llm_factory=llm_factory)
        judge_passed = final.passed
    return CaseOutcome(
        case_id=case.id,
        agent=case.agent,
        passed=final.passed,
        details=final.details,
        score=final.score,
        answer=answer,
        rule_passed=True,
        judge_passed=judge_passed,
    )


async def run_suite(
    suite: W9Suite,
    *,
    llm: LLMPort | None = None,
    supplied_answers: Mapping[str, str] | None = None,
    llm_factory: EvalJudgeClientFactory | None = None,
    case_ids: set[str] | None = None,
) -> SuiteReport:
    cases = load_cases(suite)
    if case_ids is not None:
        cases = tuple(c for c in cases if c.id in case_ids)
    outcomes: list[CaseOutcome] = []
    for case in cases:
        outcomes.append(  # noqa: PERF401 — sequential await; list-comp cannot await
            await _run_one(
                case,
                llm=llm,
                supplied_answers=supplied_answers,
                llm_factory=llm_factory,
            )
        )
    buckets: dict[str, list[bool]] = defaultdict(list)
    for case, outcome in zip(cases, outcomes, strict=True):
        buckets[_group_key(case)].append(outcome.passed)
    rates = {key: (sum(1 for x in vals if x) / len(vals) if vals else 0.0) for key, vals in buckets.items()}
    return SuiteReport(suite=suite, outcomes=tuple(outcomes), pass_rate_by_key=rates)


__all__ = ["CaseOutcome", "SuiteReport", "run_suite"]
