# src/palatium_ai/domain/mcp/__init__.py

"""Доменные MCP-модели.

Lazy ``__getattr__`` so stubs can import ``external_schemas`` / ``platform_schemas``
without pulling models / auth (Docker lean image — Phase 4).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DEFAULT_MCP_JWT_ALGORITHM",
    "DEFAULT_MCP_JWT_ISSUER",
    "DEFAULT_MCP_JWT_TTL_SECONDS",
    "LOCAL_EXECUTION_SERVERS",
    "ExecutionPlanBundle",
    "ExecutionStrategy",
    "JsonRpcError",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "MCPCapabilityBinding",
    "MCPServerDescriptor",
    "MCPToolCall",
    "MCPToolDescriptor",
    "MCPToolResult",
    "MCPToolSummary",
    "ToolExecutionPlan",
    "has_local_capability",
    "mcp_audience",
    "requires_local_handler",
]


def __getattr__(name: str) -> Any:
    if name in {
        "DEFAULT_MCP_JWT_ALGORITHM",
        "DEFAULT_MCP_JWT_ISSUER",
        "DEFAULT_MCP_JWT_TTL_SECONDS",
        "mcp_audience",
    }:
        from .auth_policy import (
            DEFAULT_MCP_JWT_ALGORITHM,
            DEFAULT_MCP_JWT_ISSUER,
            DEFAULT_MCP_JWT_TTL_SECONDS,
            mcp_audience,
        )

        mapping = {
            "DEFAULT_MCP_JWT_ALGORITHM": DEFAULT_MCP_JWT_ALGORITHM,
            "DEFAULT_MCP_JWT_ISSUER": DEFAULT_MCP_JWT_ISSUER,
            "DEFAULT_MCP_JWT_TTL_SECONDS": DEFAULT_MCP_JWT_TTL_SECONDS,
            "mcp_audience": mcp_audience,
        }
    elif name in {"LOCAL_EXECUTION_SERVERS", "has_local_capability", "requires_local_handler"}:
        from .execution_policy import (
            LOCAL_EXECUTION_SERVERS,
            has_local_capability,
            requires_local_handler,
        )

        mapping = {
            "LOCAL_EXECUTION_SERVERS": LOCAL_EXECUTION_SERVERS,
            "has_local_capability": has_local_capability,
            "requires_local_handler": requires_local_handler,
        }
    elif name in {
        "ExecutionPlanBundle",
        "ExecutionStrategy",
        "JsonRpcError",
        "JsonRpcRequest",
        "JsonRpcResponse",
        "MCPCapabilityBinding",
        "MCPServerDescriptor",
        "MCPToolCall",
        "MCPToolDescriptor",
        "MCPToolResult",
        "MCPToolSummary",
        "ToolExecutionPlan",
    }:
        from .models import (
            ExecutionPlanBundle,
            ExecutionStrategy,
            JsonRpcError,
            JsonRpcRequest,
            JsonRpcResponse,
            MCPCapabilityBinding,
            MCPServerDescriptor,
            MCPToolCall,
            MCPToolDescriptor,
            MCPToolResult,
            MCPToolSummary,
            ToolExecutionPlan,
        )

        mapping = {
            "ExecutionPlanBundle": ExecutionPlanBundle,
            "ExecutionStrategy": ExecutionStrategy,
            "JsonRpcError": JsonRpcError,
            "JsonRpcRequest": JsonRpcRequest,
            "JsonRpcResponse": JsonRpcResponse,
            "MCPCapabilityBinding": MCPCapabilityBinding,
            "MCPServerDescriptor": MCPServerDescriptor,
            "MCPToolCall": MCPToolCall,
            "MCPToolDescriptor": MCPToolDescriptor,
            "MCPToolResult": MCPToolResult,
            "MCPToolSummary": MCPToolSummary,
            "ToolExecutionPlan": ToolExecutionPlan,
        }
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = mapping[name]
    globals()[name] = value
    return value
