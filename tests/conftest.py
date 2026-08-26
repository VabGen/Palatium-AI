# tests/conftest.py

"""Общие фикстуры для тестов."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
)
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolDescriptor, MCPToolResult


class FakeLLMPort:
    """In-memory LLMPort для unit-тестов."""

    def __init__(self, content: str, *, model: str = "test-model") -> None:
        self._content = content
        self._model = model
        self.calls: list[list[ChatMessage]] = []

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        return LLMCompletion(content=self._content, model=model or self._model)

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        yield LLMStreamDelta(content=self._content)


class SequentialFakeLLMPort:
    """LLMPort, который отдаёт ответы по очереди."""

    def __init__(self, responses: list[str], *, model: str = "test-model") -> None:
        self._responses = responses
        self._model = model
        self.calls: list[list[ChatMessage]] = []
        self._index = 0

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        if self._index >= len(self._responses):
            raise RuntimeError("SequentialFakeLLMPort has no more responses")
        content = self._responses[self._index]
        self._index += 1
        return LLMCompletion(content=content, model=model or self._model)

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        completion = await self.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        yield LLMStreamDelta(content=completion.content)


class FakeMCPRegistry:
    """In-memory MCP registry for unit-tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, MCPToolCall]] = []
        self._tools = {
            "edms": [
                MCPToolDescriptor(
                    name="search_documents",
                    description="Search EDMS documents by query string.",
                    inputSchema={
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                    annotations={"readOnlyHint": True},
                )
            ]
        }

    def list_servers(self) -> list[str]:
        """Возвращает список серверов."""
        return list(self._tools.keys())

    async def list_tools(self, server_name: str, *, force_refresh: bool = False) -> list[MCPToolDescriptor]:
        """Возвращает tools указанного тестового сервера."""
        _ = force_refresh
        return self._tools[server_name]

    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        """Запоминает вызов и возвращает stub content."""
        self.calls.append((server_name, tool_call))
        return MCPToolResult(
            content=[{"type": "text", "text": f"Stub MCP result for {tool_call.arguments.get('query', '')}"}],
            isError=False,
        )


@pytest.fixture
def sample_agent_config() -> AgentConfig:
    """AgentConfig с одним разрешённым инструментом."""
    return AgentConfig(
        name="test_worker",
        role="analyst",
        model_tier="small",
        temperature=0.0,
        allowed_tools=("search",),
        timeout_seconds=5,
        max_retries=1,
        confidence_threshold=0.7,
    )
