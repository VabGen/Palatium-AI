# src/palatium_ai/application/agents/evals/judge_client.py

"""LLM client factory for nightly eval judge (040 — separate provider from generator).

The concrete LLM adapter is built by the caller (composition root / eval script)
and injected as ``EvalJudgeClientFactory``: rule 000 forbids ``application/``
importing ``infrastructure/`` directly.
"""

from __future__ import annotations

import os

from collections.abc import Callable

from palatium_ai.domain.ports.llm import LLMPort

#: ``provider name → LLMPort``. Built from ``infrastructure.llm.factory`` at the
#: composition root (``application/wiring``, ``application/bootstrap``, scripts).
EvalJudgeClientFactory = Callable[[str], LLMPort]

_SUPPORTED = frozenset({"openai", "anthropic", "ollama", "qwen"})


def resolve_judge_provider() -> str:
    provider = os.environ.get("PALATIUM_EVAL_JUDGE_PROVIDER", "").strip().lower()
    if not provider:
        msg = "PALATIUM_EVAL_JUDGE_PROVIDER is required for live llm_judge"
        raise ValueError(msg)
    if provider not in _SUPPORTED:
        msg = f"unsupported judge provider: {provider}"
        raise ValueError(msg)
    return provider


def resolve_judge_model() -> str | None:
    model = os.environ.get("PALATIUM_EVAL_JUDGE_MODEL", "").strip()
    return model or None


def assert_provider_independence(*, judge_provider: str, generator_provider: str | None) -> None:
    if not generator_provider:
        return
    if judge_provider.lower() == generator_provider.strip().lower():
        msg = "judge provider must differ from generator provider (040)"
        raise ValueError(msg)


def create_eval_judge_llm(factory: EvalJudgeClientFactory) -> LLMPort:
    """Build the judge client for ``PALATIUM_EVAL_JUDGE_PROVIDER`` via injected factory."""
    return factory(resolve_judge_provider())
