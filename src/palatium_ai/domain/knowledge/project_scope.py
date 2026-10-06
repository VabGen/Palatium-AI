# src/palatium_ai/domain/knowledge/project_scope.py

"""Project KB scoping helpers (G09) — shared by ingest id and search filter."""

from __future__ import annotations


def project_source_document_prefix(project_id: str) -> str:
    """Prefix for ``source_document_id`` values belonging to one project."""
    cleaned = project_id.strip()
    if not cleaned:
        msg = "project_id must be non-empty"
        raise ValueError(msg)
    return f"project:{cleaned}:"


__all__ = ["project_source_document_prefix"]
