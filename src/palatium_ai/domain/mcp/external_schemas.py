# src/palatium_ai/domain/mcp/external_schemas.py

"""Frozen pydantic I/O for external MCP stubs — platform pin source of truth (070)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EdmsSearchDocumentsInput(BaseModel):
    """Input for ``mcp:edms.search_documents``."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Search string for EDMS documents.",
    )


class EdmsArchiveDocumentInput(BaseModel):
    """Input for ``mcp:edms.archive_document`` (EDMS write; not canonical ``ingest_document``)."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(
        min_length=1,
        max_length=128,
        description="EDMS document identifier to archive.",
    )


class AnalyticsSalesMetricsInput(BaseModel):
    """Input for ``mcp:analytics.get_sales_metrics``."""

    model_config = ConfigDict(frozen=True)

    period: str = Field(
        min_length=1,
        max_length=64,
        description="Reporting period (e.g. 2025-Q1).",
    )


def pinned_input_schema(model: type[BaseModel]) -> dict[str, object]:
    """Build stable JSON Schema 2020-12 dict for platform fingerprinting."""
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


EDMS_SEARCH_DOCUMENTS_SCHEMA = pinned_input_schema(EdmsSearchDocumentsInput)
EDMS_ARCHIVE_DOCUMENT_SCHEMA = pinned_input_schema(EdmsArchiveDocumentInput)
ANALYTICS_SALES_METRICS_SCHEMA = pinned_input_schema(AnalyticsSalesMetricsInput)

__all__ = [
    "ANALYTICS_SALES_METRICS_SCHEMA",
    "EDMS_ARCHIVE_DOCUMENT_SCHEMA",
    "EDMS_SEARCH_DOCUMENTS_SCHEMA",
    "AnalyticsSalesMetricsInput",
    "EdmsArchiveDocumentInput",
    "EdmsSearchDocumentsInput",
    "pinned_input_schema",
]
