# src/palatium_ai/core/logging/agent_schema.py

"""Single structured agent-log schema (W8.1) — extend structlog, do not fork."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

AGENT_LOG_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "ts",
        "level",
        "agent",
        "run_id",
        "trace_id",
        "turn_id",
        "event",
        "payload",
    }
)


class AgentLogEvent(BaseModel):
    """Canonical agent log record — all agent events should be coercible to this."""

    model_config = ConfigDict(extra="allow")

    ts: str
    level: str
    agent: str
    run_id: str
    trace_id: str
    turn_id: str
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


def validate_agent_log_event(event: Mapping[str, Any]) -> AgentLogEvent:
    missing = AGENT_LOG_REQUIRED_KEYS - set(event)
    if missing:
        msg = f"agent log missing keys: {sorted(missing)}"
        raise ValueError(msg)
    return AgentLogEvent.model_validate(dict(event))


def normalize_agent_log_fields(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Map existing structlog fields onto the W8.1 schema without a second logger."""
    if "ts" not in event_dict and "timestamp" in event_dict:
        event_dict["ts"] = event_dict["timestamp"]
    turn = event_dict.get("turn_id") or event_dict.get("run_id") or ""
    if turn and "run_id" not in event_dict:
        event_dict["run_id"] = turn
    if turn and "turn_id" not in event_dict:
        event_dict["turn_id"] = turn
    if "payload" not in event_dict:
        reserved = AGENT_LOG_REQUIRED_KEYS | {"timestamp", "logger", "level"}
        event_dict["payload"] = {k: v for k, v in event_dict.items() if k not in reserved and k != "event"}
    return event_dict


__all__ = [
    "AGENT_LOG_REQUIRED_KEYS",
    "AgentLogEvent",
    "normalize_agent_log_fields",
    "validate_agent_log_event",
]
