# src/palatium_ai/application/agents/evals/__init__.py

"""Agent eval runner and baseline gate (075).

Do **not** eagerly import ``runner`` / ``cassette`` here: production
``Harness.call_llm`` loads ``constitution_hash.prompt_file_version`` through
this package, and Docker runtime images ship without ``tests/fixtures/llm``.
Eager cassette root discovery at import time killed every non-stream LLM call
(2026-11-11).
"""

from __future__ import annotations

from typing import Any

from .report import AgentEvalReport, EvalSuiteReport, TaskEvalReport

__all__ = [
    "AgentEvalReport",
    "EvalSuiteReport",
    "TaskEvalReport",
    "build_suite_report",
    "load_nightly_baseline",
    "load_nightly_tasks",
    "run_agent_evals",
    "run_all_agent_evals",
    "run_all_nightly_evals",
]

_RUNNER_EXPORTS = frozenset(__all__) - {
    "AgentEvalReport",
    "EvalSuiteReport",
    "TaskEvalReport",
}


def __getattr__(name: str) -> Any:
    if name in _RUNNER_EXPORTS:
        from . import runner as _runner

        return getattr(_runner, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
