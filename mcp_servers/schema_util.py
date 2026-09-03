# mcp_servers/schema_util.py

"""Shared JSON Schema builder for MCP stub inputSchema (must match platform pins)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel


def pinned_input_schema(model: type[BaseModel]) -> dict[str, object]:
    """Build stable JSON Schema 2020-12 dict aligned with platform fingerprints."""
    raw = model.model_json_schema()
    properties: dict[str, object] = {}
    for name, spec in raw.get("properties", {}).items():
        if not isinstance(spec, dict):
            continue
        entry: dict[str, object] = {"type": "string"}
        if "description" in spec:
            entry["description"] = spec["description"]
        if "minLength" in spec:
            entry["minLength"] = spec["minLength"]
        if "maxLength" in spec:
            entry["maxLength"] = spec["maxLength"]
        properties[name] = entry
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(raw.get("required", [])),
        "additionalProperties": False,
    }
