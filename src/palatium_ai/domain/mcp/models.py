# src/palatium_ai/domain/mcp/models.py

"""Доменные модели MCP: JSON-RPC 2.0 + JSON Schema 2020-12."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from palatium_ai.domain.policies.types import ExecutionStrategy as ExecutionStrategy

JsonRpcVersion = Literal["2.0"]


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


class MCPToolSummary(BaseModel):
    """Lightweight tool card for discovery/planning (Anthropic progressive disclosure).

    Full ``inputSchema`` is loaded only when building arguments / calling the tool.
    Wire form may use ``propertyNames`` when the server omitted ``inputSchema``.
    """

    model_config = {"frozen": True, "populate_by_name": True}

    name: str = Field(min_length=1)
    description: str = Field(default="", min_length=0)
    side_effect: Literal["read", "write", "unknown"] | None = None
    risk_tier: Literal["low", "medium", "high"] | None = Field(default=None, alias="riskTier")
    property_names: tuple[str, ...] = Field(default=(), alias="propertyNames")


class MCPToolDescriptor(BaseModel):
    """Описание MCP tool через JSON Schema 2020-12."""

    model_config = {"frozen": True, "populate_by_name": True}

    name: str = Field(min_length=1)
    description: str = Field(default="", min_length=0)
    input_schema: dict[str, object] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("input_schema", "inputSchema"),
        serialization_alias="inputSchema",
    )
    annotations: dict[str, object] | None = None
    side_effect: Literal["read", "write", "unknown"] | None = None
    risk_tier: Literal["low", "medium", "high"] | None = Field(
        default=None,
        validation_alias=AliasChoices("risk_tier", "riskTier"),
        serialization_alias="riskTier",
    )

    def to_summary(self) -> MCPToolSummary:
        """Progressive disclosure: name/description/risk without full inputSchema."""
        properties = self.input_schema.get("properties", {})
        property_names = tuple(str(key) for key in properties) if isinstance(properties, dict) else ()
        return MCPToolSummary(
            name=self.name,
            description=self.description,
            side_effect=self.side_effect,
            risk_tier=self.risk_tier,
            property_names=property_names,
        )


class MCPToolCall(BaseModel):
    """Вызов MCP tool."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    """Результат MCP tool call."""

    model_config = {"frozen": True, "populate_by_name": True}

    content: list[dict[str, object]] = Field(default_factory=list)
    is_error: bool = Field(
        default=False,
        validation_alias=AliasChoices("is_error", "isError"),
        serialization_alias="isError",
    )


class MCPServerDescriptor(BaseModel):
    """Описание доступного MCP сервера."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class MCPCapabilityBinding(BaseModel):
    """Связка capability -> server/tool (+ platform HITL metadata when known)."""

    model_config = {"frozen": True}

    capability: str = Field(min_length=1)
    server_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    description: str = Field(default="", min_length=0)
    side_effect: Literal["read", "write", "unknown"] = "unknown"
    risk_tier: Literal["low", "medium", "high"] = "medium"
    requires_hitl: bool = True


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
