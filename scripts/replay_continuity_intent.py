"""Replay ContinuityPolicy + Intent on a Contextualizer fixture (Variant 1 step 4).

When isolated Contextualizer does not reproduce draft→format, run the next layer:

1. Contextualizer (live)
2. IntentClassifier with ``continuation_kind`` hint (live)
3. ContinuityPolicy.resolve → EffectiveRoutingIntent

Usage:
  poetry run python scripts/replay_continuity_intent.py
  poetry run python scripts/replay_continuity_intent.py --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import SecretStr

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_bridge import (
    contextualizer_output_to_task_result,
    contextualizer_to_agent_input,
    intent_output_to_task_result,
    intent_to_agent_input,
)
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.domain.agents.intent import IntentClassifierInput
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput, ContextualizerOutput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies import ContinuityPolicy
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FIXTURE = _ROOT / "tests" / "fixtures" / "contextualizer_replay" / "turn1_draft_reply.json"
_LIVE_ENV_KEYS = ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_DEFAULT_MODEL")


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


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    for key in ("user_text", "dialog"):
        if key not in payload:
            raise ValueError(f"fixture missing {key!r}: {path}")
    return payload


def _classify_route(*, task_kinds: list[str], bug_task: str = "response_formatting") -> str:
    unique = set(task_kinds)
    if unique == {bug_task}:
        return "reproduced"
    if bug_task not in unique:
        return "not_reproduced"
    return "mixed"


async def _run_once(
    *,
    contextualizer: ContextualizerAgent,
    intent_agent: IntentClassifierAgent,
    fixture: dict[str, Any],
    run_idx: int,
) -> dict[str, Any]:
    thread_id = f"replay-ci-{fixture.get('id', 'case')}-{run_idx}"
    user_text = str(fixture["user_text"])
    dialog = _window(thread_id, list(fixture["dialog"]))
    has_prior = any(turn.role == "assistant" for turn in dialog.turns)

    ctx_input = ContextualizerInput(
        task_id=str(uuid4()),
        user_text=user_text,
        dialog_window=dialog,
        memory_hints=tuple(fixture.get("memory_hints") or ()),
        prompt_budget=MemoryPromptBudget(),
        task_kind=str(fixture.get("task_kind") or "knowledge_request"),  # type: ignore[arg-type]
        requires_mcp=bool(fixture.get("requires_mcp", False)),
    )
    started = time.perf_counter()
    ctx_agent_out = await contextualizer._harness.execute_with_guardrails(
        contextualizer,
        contextualizer_to_agent_input(ctx_input, trace_id="replay-ci", thread_id=thread_id),
    )
    ctx_result = contextualizer_output_to_task_result(
        ctx_agent_out,
        task_id=ctx_input.task_id,
        agent_role=contextualizer.config.role,
    )
    ctx_out = ctx_result.output
    if not isinstance(ctx_out, ContextualizerOutput):
        return {
            "run": run_idx,
            "error": ctx_result.error or "contextualizer_empty",
            "continuation_kind": None,
            "intent_task_kind": None,
            "effective_task_kind": None,
        }

    intent_input = IntentClassifierInput(
        task_id=str(uuid4()),
        text=user_text,
        continuation_kind=ctx_out.continuation_kind,
        has_prior_dialog=has_prior,
    )
    intent_agent_out = await intent_agent._harness.execute_with_guardrails(
        intent_agent,
        intent_to_agent_input(intent_input, trace_id="replay-ci", thread_id=thread_id),
    )
    intent_result = intent_output_to_task_result(
        intent_agent_out,
        task_id=intent_input.task_id,
        agent_role=intent_agent.config.role,
    )
    raw_intent = intent_result.output
    effective = ContinuityPolicy.resolve(
        contextualizer=ctx_out,
        dialog=dialog,
        raw_intent=raw_intent,
        has_turn_attachments=False,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    return {
        "run": run_idx,
        "latency_ms": latency_ms,
        "continuation_kind": ctx_out.continuation_kind,
        "ctx_confidence": ctx_out.confidence,
        "ctx_rewritten_query": ctx_out.rewritten_query,
        "intent_task_kind": None if raw_intent is None else raw_intent.task_kind,
        "intent_requires_mcp": None if raw_intent is None else raw_intent.requires_mcp,
        "intent_confidence": None if raw_intent is None else raw_intent.confidence,
        "effective_task_kind": effective.task_kind,
        "effective_continuation_kind": effective.continuation_kind,
        "effective_requires_mcp": effective.requires_mcp,
        "effective_reasoning": effective.reasoning,
        "error": None,
    }


def _fixture_label(fixture_path: Path) -> str:
    return str(fixture_path.relative_to(_ROOT)) if fixture_path.is_relative_to(_ROOT) else str(fixture_path)


def _write_report(report: dict[str, Any], *, fixture_id: object) -> Path:
    out_dir = _ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"replay_continuity_intent_{fixture_id or 'case'}_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


async def _async_main(
    *,
    fixture: dict[str, Any],
    fixture_path: Path,
    runs: int,
) -> dict[str, Any]:
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        raise RuntimeError("QWEN_API_KEY missing; cannot replay")

    base = os.environ.get("QWEN_BASE_URL", "").strip()
    model = os.environ.get("QWEN_DEFAULT_MODEL", "").strip() or "generative-model"
    adapter = LiteLLMAdapter(QwenLLMConfig(api_key=SecretStr(key), base_url=base, default_model=model))
    harness = Harness(llm=adapter)
    ctx_cfg = CONTEXTUALIZER_CONFIG.model_copy(
        update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model},
    )
    intent_cfg = INTENT_CLASSIFIER_CONFIG.model_copy(
        update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model},
    )
    contextualizer = ContextualizerAgent(harness, ctx_cfg)
    intent_agent = IntentClassifierAgent(harness, intent_cfg)

    print(f"fixture={fixture_path}")
    print(f"id={fixture.get('id')} runs={runs}")
    rows: list[dict[str, Any]] = []
    for idx in range(1, runs + 1):
        print(f"run {idx}/{runs} ...", flush=True)
        row = await _run_once(
            contextualizer=contextualizer,
            intent_agent=intent_agent,
            fixture=fixture,
            run_idx=idx,
        )
        rows.append(row)
        print(
            f"  ctx={row.get('continuation_kind')} "
            f"intent={row.get('intent_task_kind')} "
            f"effective={row.get('effective_task_kind')} "
            f"latency_ms={row.get('latency_ms')}",
            flush=True,
        )

    task_kinds = [str(row.get("effective_task_kind") or "null") for row in rows]
    ctx_kinds = [str(row.get("continuation_kind") or "null") for row in rows]
    intent_kinds = [str(row.get("intent_task_kind") or "null") for row in rows]
    verdict = _classify_route(task_kinds=task_kinds)
    return {
        "fixture": _fixture_label(fixture_path),
        "fixture_id": fixture.get("id"),
        "runs": runs,
        "continuation_kind_counts": dict(Counter(ctx_kinds)),
        "intent_task_kind_counts": dict(Counter(intent_kinds)),
        "effective_task_kind_counts": dict(Counter(task_kinds)),
        "verdict": verdict,
        "rows": rows,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    _load_env()
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        print("QWEN_API_KEY missing; cannot replay")
        return 2
    fixture_path = Path(args.fixture).resolve()
    fixture = _load_fixture(fixture_path)
    report = asyncio.run(
        _async_main(fixture=fixture, fixture_path=fixture_path, runs=max(1, int(args.runs))),
    )
    out_path = _write_report(report, fixture_id=fixture.get("id"))
    print("---")
    print(f"continuation_kind_counts={report['continuation_kind_counts']}")
    print(f"intent_task_kind_counts={report['intent_task_kind_counts']}")
    print(f"effective_task_kind_counts={report['effective_task_kind_counts']}")
    print(f"verdict={report['verdict']} (bug=effective response_formatting)")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
