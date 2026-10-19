"""Manual Formatter smoke against the corporate model.

Run:
  uv run pytest -m live_formatter -q

Credentials come from the process environment or env/.env (QWEN_API_KEY, QWEN_BASE_URL).
CI does not select this marker.

Covers both contracts the Formatter ships:
* legacy — GFM Markdown stream, parsed into ContentDocument (repair loop);
* schema_first — provider-enforced ``response_format=json_schema`` ContentDocument.
"""

from __future__ import annotations

import os

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from pydantic import BaseModel, SecretStr

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.agents.formatter.parsing import build_formatter_user_message
from palatium_ai.application.agents.formatter.prompts import FORMATTER_SYSTEM_PROMPT
from palatium_ai.application.agents.formatter.repair import generate_document
from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.content import CalloutBlock, ContentDocument, HeadingBlock, KeyValueBlock, ListBlock
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

if TYPE_CHECKING:
    from palatium_ai.domain.agents.formatter import FormatterInput

pytestmark = [
    pytest.mark.live,
    pytest.mark.live_formatter,
    # LiteLLM emits this while building the OpenAI payload; pytest filterwarnings=error
    # would turn it into a failed call before the model answers.
    pytest.mark.filterwarnings(
        "ignore:Item 'summary' on TypedDict class 'ChatCompletionReasoningItem':UserWarning",
    ),
]


_LIVE_ENV_KEYS = ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_DEFAULT_MODEL")


def _load_env_file() -> None:
    """Prefer env/.env over the empty or example defaults conftest already applied.

    tests/conftest.py setdefault's env/.env.example before collection. Those
    placeholders (empty key, public dashscope URL, qwen-turbo) must not hide
    the local corporate endpoint.
    """
    root = Path(__file__).resolve().parents[2]
    env_path = root / "env" / ".env"
    if not env_path.is_file():
        return
    from dotenv import dotenv_values

    example = dotenv_values(root / "env" / ".env.example")
    real = dotenv_values(env_path)
    for key in _LIVE_ENV_KEYS:
        real_value = (real.get(key) or "").strip()
        if not real_value:
            continue
        current = os.environ.get(key, "").strip()
        example_value = (example.get(key) or "").strip()
        if not current or current == example_value:
            os.environ[key] = real_value


def _payload(final_text: str, *, style_hint: str, choice: bool = False) -> dict[str, object]:
    return {
        "final_text": final_text,
        "style_hint": style_hint,
        "task_kind": "knowledge_request",
        "response_locale": "en-US",
        "format_hints": {
            "requires_review": False,
            "requires_user_choice": choice,
            "underspecification_kind": "discrete_choice" if choice else "none",
            "revision_feedback": None,
        },
    }


def _agent(*, mode: str = "legacy") -> FormatterAgent:
    _load_env_file()
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        pytest.skip("QWEN_API_KEY is required for live_formatter")
    base = os.environ.get("QWEN_BASE_URL", "").strip() or "http://127.0.0.1:9/v1"
    model = os.environ.get("QWEN_DEFAULT_MODEL", "").strip() or "generative-model"
    adapter = LiteLLMAdapter(
        QwenLLMConfig(api_key=SecretStr(key), base_url=base, default_model=model),
    )
    config = FORMATTER_CONFIG.model_copy(update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model})
    return FormatterAgent(Harness(llm=adapter), config, mode=mode)  # type: ignore[arg-type]


def _task_input() -> FormatterInput:
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.formatter import FormatterInput
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    return FormatterInput(
        task_id="live",
        context_packet=ContextPacket(
            task_id="live",
            user_text="hi",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="answer",
            requires_mcp=False,
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="r",
            ),
            context_summary="s",
        ),
        worker_summary="Done.",
        response_locale="en-US",
    )


async def _compile_legacy(agent: FormatterAgent, payload: dict[str, object]) -> ContentDocument:
    messages = [
        ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
        ChatMessage(role="user", content=build_formatter_user_message(payload)),
    ]
    return await generate_document(
        harness=agent._harness,
        config=agent.config,
        messages=messages,
        task_input=_task_input(),
        max_tokens=2048,
        worker_summary="Done.",
        agent_role=FORMATTER_CONFIG.role,
    )


async def _compile_schema_first(agent: FormatterAgent) -> ContentDocument:
    """Drive the real dispatch: agent.run() → _run_schema_first → json_schema call."""
    task_input = _task_input()
    agent_input = AgentInput(
        task_id=UUID(int=1),
        trace_id="live",
        instruction="format the worker draft",
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "worker_summary": task_input.worker_summary or "",
            "response_locale": task_input.response_locale,
        },
    )
    output = await agent.run(agent_input)
    assert output.status in {"success", "partial"}, output.error_message
    assert isinstance(output.output, ContentDocument)
    return output.output


@pytest.mark.asyncio()
async def test_live_status_is_one_callout() -> None:
    document = await _compile_legacy(_agent(), _payload("Done. No errors.", style_hint="brand_sections_icons"))
    assert len(document.blocks) == 1
    assert isinstance(document.blocks[0], CalloutBlock)


@pytest.mark.asyncio()
async def test_live_sections_have_headings_and_a_list() -> None:
    text = (
        "Report overview: context A.\n"
        "Issues: first issue detail; second issue detail.\n"
        "Next actions: action one; action two.\n"
        "Risk if ignored: consequence."
    )
    document = await _compile_legacy(_agent(), _payload(text, style_hint="brand_sections_icons"))
    headings = [block for block in document.blocks if isinstance(block, HeadingBlock)]
    lists = [block for block in document.blocks if isinstance(block, ListBlock)]
    assert len(headings) >= 2
    assert lists


@pytest.mark.asyncio()
async def test_live_metrics_are_a_kv_block() -> None:
    text = "Alpha: 10 units. Beta: 8 units. Gamma: 2 units."
    document = await _compile_legacy(_agent(), _payload(text, style_hint="brand_sections_icons"))
    kv = [block for block in document.blocks if isinstance(block, KeyValueBlock)]
    assert kv
    assert len(kv[0].items) >= 3


@pytest.mark.asyncio()
async def test_live_choice_is_hitl_actions() -> None:
    text = "User must pick one response layout among three concrete options: Brief, Detailed, Table."
    document = await _compile_legacy(_agent(), _payload(text, style_hint="choice_cards", choice=True))
    assert document.meta.interaction == "choice"
    assert len(document.actions) >= 3


@pytest.mark.asyncio()
async def test_live_schema_first_returns_a_valid_document() -> None:
    """response_format=json_schema path: provider returns a typed ContentDocument."""
    document = await _compile_schema_first(_agent(mode="schema_first"))
    assert document.blocks
    assert document.locale == "en-US"
    assert document.meta.kind in {
        "analysis",
        "recommendation",
        "response",
        "letter",
        "memo",
        "guide",
        "report",
        "faq",
    }


class _GarbageThenReal:
    """First completion is invalid JSON; the repair call hits the real adapter."""

    def __init__(self, inner: LiteLLMAdapter) -> None:
        self._inner = inner
        self.calls = 0
        self.formats: list[object] = []

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMCompletion:
        self.calls += 1
        self.formats.append(response_format)
        if self.calls == 1:
            return LLMCompletion(content="{not-json", model="probe")
        return await self._inner.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.asyncio()
async def test_live_repair_accepts_a_schema_document() -> None:
    _load_env_file()
    key = os.environ.get("QWEN_API_KEY", "").strip()
    if not key:
        pytest.skip("QWEN_API_KEY is required for live_formatter")
    base = os.environ.get("QWEN_BASE_URL", "").strip() or "http://127.0.0.1:9/v1"
    model = os.environ.get("QWEN_DEFAULT_MODEL", "").strip() or "generative-model"
    inner = LiteLLMAdapter(QwenLLMConfig(api_key=SecretStr(key), base_url=base, default_model=model))
    port = _GarbageThenReal(inner)
    config = FORMATTER_CONFIG.model_copy(update={"max_retries": 1, "timeout_seconds": 120, "llm_model": model})
    agent = FormatterAgent(Harness(llm=port), config)  # type: ignore[arg-type]
    messages = [
        ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=build_formatter_user_message(_payload("Done. No errors.", style_hint="brand_sections_icons")),
        ),
    ]
    document = await generate_document(
        harness=agent._harness,
        config=agent.config,
        messages=messages,
        task_input=_task_input(),
        max_tokens=2048,
        worker_summary="Done.",
        agent_role=FORMATTER_CONFIG.role,
    )
    assert document.blocks
    assert port.formats == ["text", "text"] or port.formats == ["text"]
