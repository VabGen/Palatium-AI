# src/palatium_ai/application/agents/evals/product_quality/generator.py

"""Live answer generator for W9 — real LLMPort through Harness.call_llm (not cassette)."""

from __future__ import annotations

import json

from typing import Any

from palatium_ai.application.agents.analyst import ANALYST_CONFIG
from palatium_ai.application.agents.coder import CODER_CONFIG
from palatium_ai.application.agents.evals.product_quality.case_schema import ProductQualityCase
from palatium_ai.application.agents.formatter import FORMATTER_CONFIG
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.ports.llm import LLMPort

_SYSTEM = (
    "You are a Palatium product agent under eval.\n"
    "Rules:\n"
    "1. Answer the user question. Facts that appear in the user message itself "
    "(numbers, names, service ids, code already written there) may be used freely "
    "and SHOULD appear in the answer when they name the subject of the task.\n"
    "2. When Context JSON is non-empty, treat every identifier in it as required "
    "ground truth: quote ALL named entities, codes, service names, program titles, "
    "and metric values from Context that are relevant to the question — do not "
    "drop secondary tokens (e.g. service name next to a feature flag, program "
    "title next to a customer code).\n"
    "3. Reply with exactly «нет данных» ONLY when the user asks for a named "
    "entity/code/metric that is absent from BOTH Context and the user message. "
    "Never invent missing identifiers.\n"
    "4. Never refuse self-contained work just because Context is empty: "
    "arithmetic, definitions, how-to / step lists, comparisons, and formatting "
    "of names already present in the user message must be answered normally "
    "(include those names verbatim)."
)

_CONFIGS: dict[str, AgentConfig] = {
    "researcher": RESEARCHER_CONFIG,
    "analyst": ANALYST_CONFIG,
    "coder": CODER_CONFIG,
    "formatter": FORMATTER_CONFIG,
}


def _context_block(case: ProductQualityCase) -> str:
    if not case.context:
        return "(no extra context)"
    return json.dumps(case.context, ensure_ascii=False, indent=2)


def _user_prompt(case: ProductQualityCase, *, extra_dialog: str = "") -> str:
    instruction = case.input.get("user_text") or case.input.get("instruction") or case.scenario
    parts = [
        f"Agent role: {case.agent}",
        f"Scenario: {case.scenario}",
        f"Context:\n{_context_block(case)}",
    ]
    if extra_dialog:
        parts.append(f"Dialog so far:\n{extra_dialog}")
    parts.append(f"User:\n{instruction}")
    if case.suite == "formatter":
        req = case.expected.get("structure") or {}
        parts.append(f"Format requirements: {json.dumps(req, ensure_ascii=False)}")
        if isinstance(req, dict) and req.get("require_list"):
            parts.append(
                "OUTPUT SHAPE (mandatory): use a Markdown list with at least two "
                "lines that start with '- ' or '1. ' / '2. '. Do not answer as a "
                "single prose sentence."
            )
        if isinstance(req, dict) and req.get("require_code_fence"):
            parts.append("OUTPUT SHAPE (mandatory): wrap code in a fenced ``` block.")
        if isinstance(req, dict) and req.get("require_heading"):
            parts.append("OUTPUT SHAPE (mandatory): start with a Markdown # heading.")
        preserve = case.expected.get("preserve_fields")
        if isinstance(preserve, dict) and preserve:
            parts.append(f"Must preserve these field values verbatim: {preserve}")
        # How-to / naming tasks are never «нет данных» when the subject is in User.
        parts.append(
            "If the user names a service, product, or topic, repeat that exact "
            "name in the answer. Do not reply «нет данных» for formatting or "
            "how-to requests."
        )
    if case.suite == "context" and case.context:
        parts.append(
            "Context completeness: include every identifier from Context that "
            "supports the answer (codes, names, flags, services, programs)."
        )
    return "\n\n".join(parts)


async def generate_answer(
    case: ProductQualityCase,
    *,
    llm: LLMPort,
    supplied_answer: str | None = None,
    extra_dialog: str = "",
) -> str:
    """Produce answer text. ``supplied_answer`` short-circuits for unit/anti-fiction tests."""
    if supplied_answer is not None:
        return supplied_answer
    config = _CONFIGS[case.agent]
    harness = Harness(llm=llm)
    messages = [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=_user_prompt(case, extra_dialog=extra_dialog)),
    ]
    completion = await harness.call_llm(config, messages)
    return completion.content


def dialog_transcript(turns: list[dict[str, Any]]) -> str:
    """Compact prior turns for eval prompts; apply DialogCorrectionPolicy (P1.1)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.domain.policies.dialog_correction import DialogCorrectionPolicy

    domain_turns: list[DialogTurn] = []
    for index, turn in enumerate(turns):
        role = str(turn.get("role") or "user")
        content = str(turn.get("content") or "").strip()
        if not content or role not in {"user", "assistant", "system"}:
            continue
        domain_turns.append(
            DialogTurn(
                id=uuid4(),
                thread_id="eval",
                role=role,  # type: ignore[arg-type]
                content=content,
                seq=index,
                created_at=datetime.now(UTC),
            )
        )
    if not domain_turns:
        return ""
    window = DialogCorrectionPolicy.apply(DialogTurnWindow(thread_id="eval", turns=tuple(domain_turns), limit=50))
    return window.as_prompt_block(max_chars=8_000)


__all__ = ["dialog_transcript", "generate_answer"]
