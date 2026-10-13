# src/palatium_ai/application/agents/formatter/llm_stream.py

"""Formatter LLM stream / one-shot text completion (Hybrid SSE)."""

from __future__ import annotations

import asyncio
import contextlib

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from palatium_ai.application.agents.formatter.icon_sanitizer import sanitize_markdown_buffer
from palatium_ai.application.agents.formatter.stream_delta import FormatterMarkdownEmitter
from palatium_ai.core.logging import get_logger
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort

logger = get_logger(__name__)

DeltaCallback = Callable[[str], object]
FIRST_TOKEN_FALLBACK_SECONDS = 8.0
FALLBACK_PROSE_CHARS = 200


async def call_formatter_llm(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    max_tokens: int,
    worker_summary: str = "",
) -> tuple[LLMCompletion, str]:
    """Stream GFM when an SSE bridge is bound; otherwise one-shot text completion."""
    emitter = FormatterMarkdownEmitter.bind()
    if emitter is None:
        return await complete(harness=harness, config=config, messages=messages, max_tokens=max_tokens)

    on_delta, cancel_watch = first_token_fallback_watch(
        emitter,
        worker_summary=worker_summary,
    )
    try:
        completion, _ = await complete(
            harness=harness,
            config=config,
            messages=messages,
            max_tokens=max_tokens,
            on_delta=on_delta,
        )
    finally:
        await cancel_watch()
    markdown = emitter.finish() or sanitize_markdown_buffer(completion.content)
    return completion, markdown


async def complete(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    max_tokens: int,
    on_delta: DeltaCallback | None = None,
) -> tuple[LLMCompletion, str]:
    """Always request plain text; Markdown is parsed after the stream."""
    completion = await dispatch(
        harness=harness,
        config=config,
        messages=messages,
        max_tokens=max_tokens,
        on_delta=on_delta,
    )
    return completion, sanitize_markdown_buffer(completion.content)


async def dispatch(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    max_tokens: int,
    on_delta: DeltaCallback | None,
) -> LLMCompletion:
    if on_delta is None:
        return await harness.call_llm(
            config,
            messages,
            response_format="text",
            response_model=None,
            max_tokens=max_tokens,
        )
    return await harness.call_llm_stream(
        config,
        messages,
        response_format="text",
        response_model=None,
        on_delta=on_delta,
        max_tokens=max_tokens,
    )


def _fallback_budget_seconds() -> float:
    """Prefer agent-module constant so tests can monkeypatch ``formatter.agent``."""
    from palatium_ai.application.agents.formatter import agent as formatter_agent

    return float(formatter_agent._FIRST_TOKEN_FALLBACK_SECONDS)


def first_token_fallback_watch(
    emitter: FormatterMarkdownEmitter,
    *,
    worker_summary: str,
) -> tuple[DeltaCallback, Callable[[], Awaitable[None]]]:
    """Emit worker prose if Formatter first token exceeds 8s (Phase 2)."""
    first_token = asyncio.Event()
    prose = (worker_summary or "").strip()[:FALLBACK_PROSE_CHARS]

    async def _watch() -> None:
        if not prose:
            return
        budget = _fallback_budget_seconds()
        try:
            await asyncio.wait_for(first_token.wait(), timeout=budget)
        except TimeoutError:
            if not first_token.is_set():
                emitter.emit_fallback_prose(prose)
                logger.info(
                    "formatter.fallback_stream",
                    chars=len(prose),
                    budget_seconds=budget,
                )

    watch_task = asyncio.create_task(_watch())

    def on_delta(chunk: str) -> None:
        if chunk and not first_token.is_set():
            first_token.set()
        emitter.on_delta(chunk)

    async def cancel() -> None:
        if not first_token.is_set():
            first_token.set()
        if not watch_task.done():
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task

    return on_delta, cancel
