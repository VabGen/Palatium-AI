# src/palatium_ai/domain/mcp/models.py

"""Доменные модели MCP: JSON-RPC 2.0 + JSON Schema 2020-12."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JsonRpcVersion = Literal["2.0"]
ExecutionStrategy = Literal[
    "direct_tool_call",
    "retrieve_then_reason",
    "reason_only",
    "format_only",
    "ack_only",
    "clarify",
]


class JsonRpcError(BaseModel):
    """Ошибка JSON-RPC 2.0."""

    model_config = {"frozen": True}

    code: int
    message: str = Field(min_length=1)
    data: dict[str, object] | None = None


class JsonRpcRequest(BaseModel):
    """Запрос JSON-RPC 2.0."""

    model_config = {"frozen": True}

    jsonrpc: JsonRpcVersion = "2.0"
    method: str = Field(min_length=1)
    params: dict[str, object] | None = None
    id: str = Field(min_length=1)


class JsonRpcResponse(BaseModel):
    """Ответ JSON-RPC 2.0."""

    model_config = {"frozen": True}

    jsonrpc: JsonRpcVersion = "2.0"
    result: dict[str, object] | list[object] | str | int | float | bool | None = None
    error: JsonRpcError | None = None
    id: str | None = None


class MCPToolDescriptor(BaseModel):
    """Описание MCP tool через JSON Schema 2020-12."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1)
    description: str = Field(default="", min_length=0)
    input_schema: dict[str, object] = Field(default_factory=dict, alias="inputSchema")
    annotations: dict[str, object] | None = None
    side_effect: Literal["read", "write", "unknown"] | None = None
    risk_tier: Literal["low", "medium", "high"] | None = Field(default=None, alias="riskTier")


class MCPToolCall(BaseModel):
    """Вызов MCP tool."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    """Результат MCP tool call."""

    model_config = {"frozen": True}

    content: list[dict[str, object]] = Field(default_factory=list)
    is_error: bool = Field(default=False, alias="isError")


class MCPServerDescriptor(BaseModel):
    """Описание доступного MCP сервера."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class MCPCapabilityBinding(BaseModel):
    """Связка capability -> server/tool."""

    model_config = {"frozen": True}

    capability: str = Field(min_length=1)
    server_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    description: str = Field(default="", min_length=0)


class ToolExecutionPlan(BaseModel):
    """План tool execution, собранный до worker execution."""

    model_config = {"frozen": True}

    strategy: ExecutionStrategy
    capability: str | None = None
    server_name: str | None = None
    tool_name: str | None = None
    requires_tool_call: bool = False
    rationale: str = Field(min_length=1)


class ExecutionPlanBundle(BaseModel):
    """Набор execution steps для одного orchestration pass."""

    model_config = {"frozen": True}

    selected_strategy: ExecutionStrategy
    requires_tool_call: bool = False
    steps: tuple[ToolExecutionPlan, ...] = Field(default_factory=tuple)
