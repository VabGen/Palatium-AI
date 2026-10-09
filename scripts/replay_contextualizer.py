"""Replay Contextualizer on a captured payload (Variant 1 diagnosis).

Runs the same fixture N times against a live LLM and classifies stability:

  reproduced — every run returned ``bug_kind`` (default ``format``)
  not_reproduced — every run returned ``expect_kind`` (default ``answer``)
  mixed — both kinds (or other) appeared

Usage:
  poetry run python scripts/replay_contextualizer.py
  poetry run python scripts/replay_contextualizer.py
    --fixture tests/fixtures/contextualizer_replay/turn1_draft_reply.json
    --runs 5
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
    required = ("user_text", "dialog", "expect_kind")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"fixture missing {missing}: {path}")
    return payload


def _classify(*, kinds: list[str], expect_kind: str, bug_kind: str) -> str:
    unique = set(kinds)
    if unique == {bug_kind}:
        return "reproduced"
    if unique == {expect_kind}:
        return "not_reproduced"
    return "mixed"


async def _run_once(agent: ContextualizerAgent, fixture: dict[str, Any], *, run_idx: int) -> dict[str, Any]:
    thread_id = f"replay-{fixture.get('id', 'case')}-{run_idx}"
    task_kind = str(fixture.get("task_kind") or "knowledge_request")
    task_input = ContextualizerInput(
        task_id=str(uuid4()),
        user_text=str(fixture["user_text"]),
        dialog_window=_window(thread_id, list(fixture["dialog"])),
        memory_hints=tuple(fixture.get("memory_hints") or ()),
        prompt_budget=MemoryPromptBudget(),
        task_kind=task_kind,  # type: ignore[arg-type]
        requires_mcp=bool(fixture.get("requires_mcp", False)),
    )
    started = time.perf_counter()
    agent_input = contextualizer_to_agent_input(task_input, trace_id="replay", thread_id=thread_id)
    agent_output = await agent._harness.execute_with_guardrails(agent, agent_input)
    latency_ms = round((time.perf_counter() - started) * 1000)
    result = contextualizer_output_to_task_result(
        agent_output,
        task_id=task_input.task_id,
        agent_role=agent.config.role,
    )
    out = result.output
    row: dict[str, Any] = {
        "run": run_idx,
        "latency_ms": latency_ms,
        "status": result.status,
        "error": result.error,
        "continuation_kind": None,
        "confidence": None,
        "rewritten_query": None,
        "reasoning": None,
    }
    if out is not None:
        row["continuation_kind"] = out.continuation_kind
        row["confidence"] = out.confidence
        row["rewritten_query"] = out.rewritten_query
        row["reasoning"] = out.reasoning
        row["refers_to_prior"] = out.refers_to_prior
        row["prior_assistant_excerpt"] = out.prior_assistant_excerpt
    return row


def _fixture_label(fixture_path: Path) -> str:
    return str(fixture_path.relative_to(_ROOT)) if fixture_path.is_relative_to(_ROOT) else str(fixture_path)


def _write_report(report: dict[str, Any], *, fixture_id: object) -> Path:
    out_dir = _ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"replay_contextualizer_{fixture_id or 'case'}_{stamp}.json"
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

    expect_kind = str(fixture["expect_kind"])
    bug_kind = str(fixture.get("bug_kind") or "format")
    base = os.environ.get("QWEN_BASE_URL", "").strip()
    model = os.environ.get("QWEN_DEFAULT_MODEL", "").strip() or "generative-model"
    adapter = LiteLLMAdapter(QwenLLMConfig(api_key=SecretStr(key), base_url=base, default_model=model))
    config = CONTEXTUALIZER_CONFIG.model_copy(
        update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model},
    )
    agent = ContextualizerAgent(Harness(llm=adapter), config)

    print(f"fixture={fixture_path}")
    print(f"id={fixture.get('id')} expect={expect_kind} bug={bug_kind} runs={runs}")
    rows: list[dict[str, Any]] = []
    for idx in range(1, runs + 1):
        print(f"run {idx}/{runs} ...", flush=True)
        row = await _run_once(agent, fixture, run_idx=idx)
        rows.append(row)
        print(
            f"  kind={row['continuation_kind']} confidence={row['confidence']} "
            f"latency_ms={row['latency_ms']}",
            flush=True,
        )

    kinds = [str(row["continuation_kind"] or "null") for row in rows]
    verdict = _classify(kinds=kinds, expect_kind=expect_kind, bug_kind=bug_kind)
    counts = dict(Counter(kinds))
    return {
        "fixture": _fixture_label(fixture_path),
        "fixture_id": fixture.get("id"),
        "expect_kind": expect_kind,
        "bug_kind": bug_kind,
        "runs": runs,
        "kind_counts": counts,
        "verdict": verdict,
        "rows": rows,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument("--runs", type=int, default=5, help="Live LLM repetitions (default 5)")
    args = parser.parse_args()
    _load_env()
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        print("QWEN_API_KEY missing; cannot replay")
        return 2
    runs = int(args.runs)
    if runs < 1:
        raise ValueError("--runs must be >= 1")
    fixture_path = Path(args.fixture).resolve()
    fixture = _load_fixture(fixture_path)
    report = asyncio.run(_async_main(fixture=fixture, fixture_path=fixture_path, runs=runs))
    out_path = _write_report(report, fixture_id=fixture.get("id"))
    verdict = str(report["verdict"])
    print("---")
    print(f"kind_counts={report['kind_counts']}")
    print(f"verdict={verdict}")
    print(f"wrote {out_path}")
    if verdict == "reproduced":
        print("next: fix via prompt (draft vs format boundary)")
    elif verdict == "not_reproduced":
        print("next: widen diagnosis through Continuity/Intent (full-turn payload)")
    else:
        print("next: stabilize via few-shot (non-deterministic boundary)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
