"""Live Contextualizer baseline (Phase 0-baseline). Manual, not CI.

Writes ``artifacts/baseline_contextualizer_<YYYY-MM-DD>.jsonl``.

Usage:
  poetry run python scripts/run_contextualizer_baseline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import SecretStr

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.orchestration.agent_bridge import (
    contextualizer_output_to_task_result,
    contextualizer_to_agent_input,
)
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

_ROOT = Path(__file__).resolve().parents[1]
_LIVE_ENV_KEYS = ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_DEFAULT_MODEL")
_APPEAL = (
    "Обращение гражданина Иванова И.И.: прошу разъяснить срок рассмотрения "
    "заявления №42 от 01.09.2026 и предоставить копию решения."
)
_HITL = (
    "<<<HITL_CHOICE_RESUME kind=clarify action_id=opt_brief option_kind=custom>>>\n"
    "<<<UNTRUSTED_HITL_LABEL\nКраткий ответ\n<<<END_UNTRUSTED_HITL_LABEL>>>"
)


def _load_env() -> None:
    from dotenv import dotenv_values

    example = dotenv_values(_ROOT / "env" / ".env.example")
    real = dotenv_values(_ROOT / "env" / ".env")
    for key in _LIVE_ENV_KEYS:
        value = (real.get(key) or "").strip()
        if not value:
            continue
        current = os.environ.get(key, "").strip()
        example_value = (example.get(key) or "").strip()
        if not current or current == example_value:
            os.environ[key] = value


def _window(thread_id: str, dialog: list[dict[str, str]]) -> DialogTurnWindow:
    turns = tuple(
        DialogTurn(
            id=uuid4(),
            thread_id=thread_id,
            role=turn["role"],  # type: ignore[arg-type]
            content=turn["content"],
            seq=idx,
            created_at=datetime.now(UTC),
        )
        for idx, turn in enumerate(dialog)
    )
    return DialogTurnWindow(thread_id=thread_id, turns=turns)


def _cases() -> list[dict[str, Any]]:
    prior_doc = [
        {"role": "user", "content": "Вот текст обращения"},
        {"role": "assistant", "content": _APPEAL},
    ]
    duck = [
        {"role": "user", "content": "Хочу на ужин утку"},
        {"role": "assistant", "content": "Отлично, утка — хороший выбор."},
        {"role": "user", "content": "write python code that searches the web"},
        {
            "role": "assistant",
            "content": (
                "Пример:\nimport requests\n"
                "def search(q):\n"
                "    return requests.get('https://example.com', params={'q': q}).json()\n"
            ),
        },
    ]
    return [
        {
            "id": "1_reformat_official",
            "expect_kind": "format",
            "user_text": "перепиши это официально",
            "task_kind": "knowledge_request",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "2_reformat_translate",
            "expect_kind": "format",
            "user_text": "переведи на английский",
            "task_kind": "knowledge_request",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "3_draft_reply",
            "expect_kind": "answer",
            "user_text": "составь ответ на это обращение",
            "task_kind": "knowledge_request",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "4_draft_letter",
            "expect_kind": "answer",
            "user_text": "напиши письмо по этому",
            "task_kind": "knowledge_request",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "5_anaphora_multi_hop",
            "expect_kind": "answer",
            "user_text": "а про утку что?",
            "task_kind": "knowledge_request",
            "dialog": duck,
            "memory_hints": (),
        },
        {
            "id": "6_user_anaphora",
            "expect_kind": "answer",
            "user_text": "предложи рецепт того что я хотел на ужин",
            "task_kind": "knowledge_request",
            "dialog": duck,
            "memory_hints": (),
        },
        {
            "id": "7_new_topic",
            "expect_kind": "new_topic",
            "user_text": "расскажи анекдот",
            "task_kind": "knowledge_request",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "8_social",
            "expect_kind": "new_topic",
            "user_text": "спасибо",
            "task_kind": "social_conversation",
            "dialog": prior_doc,
            "memory_hints": (),
        },
        {
            "id": "9_clarify_legit",
            "expect_kind": "clarify",
            "user_text": "сделай это",
            "task_kind": "knowledge_request",
            "dialog": [
                {"role": "user", "content": "привет"},
                {"role": "assistant", "content": "Здравствуйте! Чем могу помочь?"},
            ],
            "memory_hints": (),
        },
        {
            "id": "10_hitl_resume",
            "expect_kind": "answer",
            "user_text": _HITL,
            "task_kind": "clarification_needed",
            "dialog": [
                {"role": "user", "content": "нужен ответ на обращение"},
                {
                    "role": "assistant",
                    "content": "Выберите формат ответа: краткий или подробный.",
                },
            ],
            "memory_hints": (),
            "expect_no_llm": True,
        },
    ]


async def _run_one(agent: ContextualizerAgent, case: dict[str, Any]) -> dict[str, Any]:
    thread_id = f"baseline-{case['id']}"
    task_kind = str(case["task_kind"])
    task_input = ContextualizerInput(
        task_id=str(uuid4()),
        user_text=case["user_text"],
        dialog_window=_window(thread_id, case["dialog"]),
        memory_hints=tuple(case.get("memory_hints") or ()),
        prompt_budget=MemoryPromptBudget(),
        task_kind=task_kind,  # type: ignore[arg-type]
        requires_mcp=False,
    )

    started = time.perf_counter()
    agent_input = contextualizer_to_agent_input(task_input, trace_id="baseline", thread_id=thread_id)
    agent_output = await agent._harness.execute_with_guardrails(agent, agent_input)
    latency_ms = round((time.perf_counter() - started) * 1000)
    result = contextualizer_output_to_task_result(
        agent_output,
        task_id=task_input.task_id,
        agent_role=agent.config.role,
    )
    out = result.output
    row: dict[str, Any] = {
        "id": case["id"],
        "expect_kind": case["expect_kind"],
        "latency_ms": latency_ms,
        "input": {
            "user_text": case["user_text"],
            "task_kind": task_kind,
            "dialog": case["dialog"],
            "memory_hints": list(case.get("memory_hints") or ()),
        },
        "output": None,
        "status": result.status,
        "error": result.error,
        "kind_match": False,
        "used_llm": not bool(case.get("expect_no_llm")),
    }
    if out is not None:
        row["output"] = {
            "rewritten_query": out.rewritten_query,
            "continuation_kind": out.continuation_kind,
            "confidence": out.confidence,
            "refers_to_prior": out.refers_to_prior,
            "prior_assistant_excerpt": out.prior_assistant_excerpt,
            "choice_slot_filled": out.choice_slot_filled,
            "reasoning": out.reasoning,
        }
        row["kind_match"] = out.continuation_kind == case["expect_kind"]
        if case.get("expect_no_llm"):
            row["used_llm"] = "HITL_CHOICE_RESUME" in out.reasoning or out.choice_slot_filled
    return row


async def main() -> int:
    _load_env()
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        print("QWEN_API_KEY missing; cannot collect live baseline")
        return 2
    base = os.environ.get("QWEN_BASE_URL", "").strip()
    model = os.environ.get("QWEN_DEFAULT_MODEL", "").strip() or "generative-model"
    adapter = LiteLLMAdapter(QwenLLMConfig(api_key=SecretStr(key), base_url=base, default_model=model))
    config = CONTEXTUALIZER_CONFIG.model_copy(
        update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model},
    )
    agent = ContextualizerAgent(Harness(llm=adapter), config)

    rows: list[dict[str, Any]] = []
    for case in _cases():
        print(f"running {case['id']} ...", flush=True)
        row = await _run_one(agent, case)
        rows.append(row)
        kind = (row.get("output") or {}).get("continuation_kind")
        print(
            f"  kind={kind} expect={case['expect_kind']} "
            f"match={row['kind_match']} latency_ms={row['latency_ms']}",
            flush=True,
        )

    out_dir = _ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"baseline_contextualizer_{datetime.now(UTC).date().isoformat()}.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    matched = sum(1 for row in rows if row["kind_match"])
    latencies = [int(row["latency_ms"]) for row in rows]
    print(f"wrote {path}")
    print(f"kind_match {matched}/{len(rows)}")
    print(f"latency_ms min={min(latencies)} max={max(latencies)} avg={sum(latencies) // len(latencies)}")
    draft = next(row for row in rows if row["id"] == "3_draft_reply")
    draft_kind = (draft.get("output") or {}).get("continuation_kind")
    print(f"draft_reply_kind={draft_kind} (expect answer; FAIL confirms bug if format)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
