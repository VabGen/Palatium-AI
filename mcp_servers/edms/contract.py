# mcp_servers/edms/contract.py

"""Frozen pydantic I/O for EDMS MCP stub — mirrors platform external_schemas."""

from __future__ import annotations

import sys

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

try:
    from schema_util import pinned_input_schema
except ImportError:
    _mcp_root = Path(__file__).resolve().parent.parent
    if str(_mcp_root) not in sys.path:
        sys.path.insert(0, str(_mcp_root))
    from schema_util import pinned_input_schema

_MAX_QUERY_CHARS = 200
_MAX_DOCUMENT_ID_CHARS = 128


class SearchDocumentsInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(
        min_length=1,
        max_length=_MAX_QUERY_CHARS,
        description="Search string for EDMS documents.",
    )


class ArchiveDocumentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str = Field(
        min_length=1,
        max_length=_MAX_DOCUMENT_ID_CHARS,
        description="EDMS document identifier to archive.",
    )


SEARCH_DOCUMENTS_INPUT_SCHEMA = pinned_input_schema(SearchDocumentsInput)
ARCHIVE_DOCUMENT_INPUT_SCHEMA = pinned_input_schema(ArchiveDocumentInput)
