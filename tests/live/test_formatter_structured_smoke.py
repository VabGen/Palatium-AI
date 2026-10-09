"""Manual Formatter smoke against the corporate model.

Run:
  poetry run pytest -m live_formatter -q

Credentials come from the process environment or env/.env (QWEN_API_KEY, QWEN_BASE_URL).
CI does not select this marker.
"""

from __future__ import annotations

import os

from pathlib import Path

import pytest

from pydantic import BaseModel, SecretStr

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.agents.formatter.parsing import build_formatter_user_message
from palatium_ai.application.agents.formatter.prompts import FORMATTER_SYSTEM_PROMPT
from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.domain.content import CalloutBlock, ContentDocument, HeadingBlock, KeyValueBlock, ListBlock
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

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


def _agent() -> FormatterAgent:
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
    return FormatterAgent(Harness(llm=adapter), config)


async def _compile(agent: FormatterAgent, payload: dict[str, object]) -> ContentDocument:
    user = build_formatter_user_message(payload)
    messages = [
        ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user),
    ]
    return await agent._generate_document(messages, max_tokens=2048)


@pytest.mark.asyncio()
async def test_live_status_is_one_callout() -> None:
    document = await _compile(_agent(), _payload("Done. No errors.", style_hint="brand_sections_icons"))
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
    document = await _compile(_agent(), _payload(text, style_hint="brand_sections_icons"))
    headings = [block for block in document.blocks if isinstance(block, HeadingBlock)]
    lists = [block for block in document.blocks if isinstance(block, ListBlock)]
    assert len(headings) >= 2
    assert lists


@pytest.mark.asyncio()
async def test_live_metrics_are_a_kv_block() -> None:
    text = "Alpha: 10 units. Beta: 8 units. Gamma: 2 units."
    document = await _compile(_agent(), _payload(text, style_hint="brand_sections_icons"))
    kv = [block for block in document.blocks if isinstance(block, KeyValueBlock)]
    assert kv
    assert len(kv[0].items) >= 3


@pytest.mark.asyncio()
async def test_live_choice_is_hitl_actions() -> None:
    text = "User must pick one response layout among three concrete options: Brief, Detailed, Table."
    document = await _compile(_agent(), _payload(text, style_hint="choice_cards", choice=True))
    assert document.meta.interaction == "choice"
    assert len(document.actions) >= 3


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
    document = await agent._generate_document(messages, max_tokens=2048)
    assert document.blocks
    assert port.formats == ["json_schema", "json_schema"]
