# tests/unit/test_offline_benchmark.py

"""Offline 100-task FakeLLM benchmark → SLA success-rate gate (Week 7)."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.sla.corpus import BenchmarkCase, build_benchmark_corpus
from palatium_ai.domain.sla.gates import evaluate_success_rate
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from tests.conftest import (
    FakeLLMPort,
    FakeMCPRegistry,
    SequentialFakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_continuation_agent,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_intent_stack,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

_HITL_HMAC = "unit-test-hitl-hmac-key-32b"  # noqa: S105


class _FakeSessionService:
    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None


def _formatter_document_json(title: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "locale": "en-US",
            "title": title,
            "blocks": [
                {"type": "heading", "level": 2, "text": title, "icon": None},
                {"type": "paragraph", "text": title},
            ],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        }
    )


def _intent_payload(case: BenchmarkCase) -> str:
    caps = ["search"] if case.requires_mcp else []
    return json.dumps(
        {
            "task_kind": case.task_kind,
            "requires_mcp": case.requires_mcp,
            "candidate_capabilities": caps,
            "confidence": 0.95,
            "reasoning": f"corpus:{case.case_id}",
        }
    )


def _service_for_case(case: BenchmarkCase) -> IntentService:
    mcp = FakeMCPRegistry() if case.requires_mcp else None
    if case.requires_mcp:
        researcher_llm: FakeLLMPort | SequentialFakeLLMPort = SequentialFakeLLMPort(
            [json.dumps({"query": case.user_text})]
        )
    else:
        researcher_llm = FakeLLMPort(
            json.dumps(
                {
                    "summary": f"answer for {case.case_id}",
                    "confidence": 0.95,
                    "sources_used": ["llm_internal_reasoning"],
                }
            )
        )

    harness, intent_agent = make_intent_stack(FakeLLMPort(_intent_payload(case)))
    graph = build_agent_graph(
        harness=harness,
        continuation_agent=make_continuation_agent(harness=harness),
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(mcp, harness=harness),
        researcher_agent=make_researcher_agent(researcher_llm, mcp, harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(
            FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
        ),
        formatter_agent=make_formatter_agent(FakeLLMPort(_formatter_document_json(case.case_id))),
        checkpointer=make_graph_checkpointer(),
    )
    return IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
    )


@pytest.mark.asyncio
async def test_offline_benchmark_100_meets_success_gate() -> None:
    corpus = build_benchmark_corpus(size=100)
    successes = 0
    failures: list[str] = []

    for case in corpus:
        service = _service_for_case(case)
        result = await service.process(text=case.user_text, thread_id=case.case_id)
        ok = result.status in {"success", "partial"} and result.output is not None
        # Tool-approval interrupt still counts as controlled success (HITL path).
        if result.status == "partial" and result.hitl_cards:
            ok = True
        if ok:
            successes += 1
        else:
            failures.append(f"{case.case_id}:{case.task_kind}:{result.status}:{result.error}")

    gate = evaluate_success_rate(successes=successes, total=len(corpus), min_rate=0.85)
    assert gate.passed, f"SLA gate failed: {gate.detail}; sample failures={failures[:5]}"
    assert successes == len(corpus), f"expected all canned turns green, got {gate.detail}"
