"""Follow-up smoke: dialog turns + Contextualizer → response_formatting (not clarify)."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import (
    FakeDialogTurnStore,
    FakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_critic_agent,
    make_dual_agent_stack,
    make_formatter_agent,
    make_graph_checkpointer,
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


def _formatter_json(title: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "locale": "ru-RU",
            "title": title,
            "blocks": [
                {"type": "heading", "level": 2, "text": title, "icon": None},
                {
                    "type": "table",
                    "columns": ["Шаг", "Деталь"],
                    "rows": [["1", "Цель"], ["2", "Повестка"]],
                },
            ],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_followup_format_uses_dialog_memory_not_clarification() -> None:
    """Bug: 'план → дай таблицей' used to become clarification without rewrite."""
    dialog = FakeDialogTurnStore()
    memory = InMemoryMemoryPort()

    # Seed prior exchange as if turn 1 already happened.
    await dialog.append_turn(thread_id="follow-1", role="user", content="Составь план встречи на завтра")
    await dialog.append_turn(
        thread_id="follow-1",
        role="assistant",
        content="План встречи:\n1. Цель\n2. Повестка\n3. Участники",
    )

    harness, contextualizer, intent_agent, pipeline_llm = make_dual_agent_stack(
        """{
              "rewritten_query": "Представь предыдущий план встречи в виде таблицы",
              "continuation_kind": "format",
              "confidence": 0.93,
              "refers_to_prior": true,
              "prior_assistant_excerpt": "План встречи:\\n1. Цель\\n2. Повестка",
              "reasoning": "format follow-up"
            }""",
        '{"task_kind": "response_formatting", "requires_mcp": false, '
        '"candidate_capabilities": ["format"], "confidence": 0.91, '
        '"reasoning": "Rewritten format request"}',
    )
    graph = build_agent_graph(
        harness=harness,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(
            FakeLLMPort('{"summary": "unused", "confidence": 0.1, "sources_used": []}'), harness=harness
        ),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(
            FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
        ),
        formatter_agent=make_formatter_agent(FakeLLMPort(_formatter_json("План встречи (таблица)"))),
        continuation_agent=contextualizer,
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
        memory_port=memory,
    )

    result = await service.process(text="дай в виде таблицы", thread_id="follow-1", task_id="t-follow")

    assert result.status == "success"
    assert result.output is not None
    assert "таблиц" in (result.output.title or "").lower() or any(
        getattr(block, "type", None) == "table" for block in result.output.blocks
    )
    # Researcher must be skipped on format route
    # (intent was response_formatting after rewrite)
    window = await dialog.list_recent_turns(thread_id="follow-1", limit=10)
    assert len(window.turns) >= 4  # prior 2 + new user + assistant
    assert window.turns[-2].role == "user"
    assert "таблиц" in window.turns[-2].content.lower()


@pytest.mark.asyncio
async def test_followup_answer_overrides_false_clarification() -> None:
    """Bug: 'когда завершение встречи' → clarify HITL despite prior schedule in dialog."""
    dialog = FakeDialogTurnStore()
    await dialog.append_turn(
        thread_id="follow-answer",
        role="user",
        content="Составь план встречи на завтра",
    )
    await dialog.append_turn(
        thread_id="follow-answer",
        role="assistant",
        content=(
            "План встречи\n• Утреннее собрание (9:00–9:30)\n• Завершение встречи (15:00–15:15) — подведение итогов"
        ),
    )

    harness, contextualizer, intent_agent, pipeline_llm = make_dual_agent_stack(
        """{
                  "rewritten_query": "Когда завершится встреча?",
                  "continuation_kind": "answer",
                  "confidence": 0.9,
                  "refers_to_prior": true,
                  "prior_assistant_excerpt": "Завершение встречи (15:00–15:15)",
                  "reasoning": "anaphora to prior schedule"
                }""",
        '{"task_kind": "clarification_needed", "requires_mcp": false, '
        '"candidate_capabilities": [], "confidence": 0.9, '
        '"reasoning": "No meeting details provided"}',
    )
    graph = build_agent_graph(
        harness=harness,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(
            FakeLLMPort(
                '{"summary": "Встреча завершается в 15:00–15:15", '
                '"confidence": 0.95, "sources_used": ["prior_context"]}'
            ),
            harness=harness,
        ),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(
            FakeLLMPort(
                '{"accuracy_score": 9, "safety_score": 10, "requires_review": false, '
                '"summary": "Answered from prior schedule"}'
            )
        ),
        formatter_agent=make_formatter_agent(
            FakeLLMPort(
                json.dumps(
                    {
                        "schema_version": 1,
                        "locale": "ru-RU",
                        "title": "Завершение встречи",
                        "blocks": [
                            {
                                "type": "paragraph",
                                "text": "Встреча завершается в 15:00–15:15.",
                            }
                        ],
                        "actions": [],
                        "meta": {
                            "confidence": 0.95,
                            "requires_review": False,
                            "source_refs": [],
                        },
                    },
                    ensure_ascii=False,
                )
            )
        ),
        continuation_agent=contextualizer,
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
        memory_port=InMemoryMemoryPort(),
    )

    result = await service.process(
        text="когда завершение встречи",
        thread_id="follow-answer",
        task_id="t-answer",
    )

    assert result.status == "success"
    assert result.requires_review is False
    assert result.output is not None
    assert "15:00" in result.output.plain_text()


@pytest.mark.asyncio
async def test_phatic_followup_skips_researcher_and_critic_llm() -> None:
    """Bug: 'привет → как дела' routed to Researcher + Critic HITL."""
    dialog = FakeDialogTurnStore()
    await dialog.append_turn(thread_id="social-follow", role="user", content="привет")
    await dialog.append_turn(thread_id="social-follow", role="assistant", content="Привет!")

    llm_researcher = FakeLLMPort('{"summary": "unused", "confidence": 0.1, "sources_used": []}')
    llm_critic = FakeLLMPort(
        '{"accuracy_score": 1, "safety_score": 1, "requires_review": true, "summary": "should not run"}'
    )
    harness, contextualizer, intent_agent, pipeline_llm = make_dual_agent_stack(
        """{
          "rewritten_query": "как дела",
          "continuation_kind": "new_topic",
          "confidence": 0.9,
          "refers_to_prior": false,
          "prior_assistant_excerpt": null,
          "reasoning": "phatic; self-contained"
        }""",
        '{"task_kind": "social_conversation", "requires_mcp": false, '
        '"candidate_capabilities": [], "confidence": 0.94, '
        '"reasoning": "Phatic follow-up after greeting"}',
    )
    graph = build_agent_graph(
        harness=harness,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(llm_researcher, harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(llm_critic),
        formatter_agent=make_formatter_agent(
            FakeLLMPort(
                json.dumps(
                    {
                        "schema_version": 1,
                        "locale": "ru-RU",
                        "title": "Ответ",
                        "blocks": [{"type": "paragraph", "text": "У меня всё хорошо, спасибо!"}],
                        "actions": [],
                        "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
                    },
                    ensure_ascii=False,
                )
            )
        ),
        continuation_agent=contextualizer,
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
        memory_port=InMemoryMemoryPort(),
    )

    result = await service.process(text="как дела", thread_id="social-follow", task_id="t-social")

    assert result.status == "success"
    assert result.requires_review is False
    assert len(llm_researcher.calls) == 0
    assert len(llm_critic.calls) == 0
    # Contextualizer runs before Intent when assistant prior exists (live continuation hints).
    assert len(pipeline_llm.calls) >= 1
