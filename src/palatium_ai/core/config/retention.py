# src/palatium_ai/core/config/retention.py

"""Global data retention windows (plans/global-retention.md).

``core`` does not import ``domain`` (000): numbers stay flat here; composition
root builds ``RetentionWindows`` for policies and adapters.
"""

from __future__ import annotations

from pydantic import Field

from .base import BaseConfig


class RetentionConfig(BaseConfig):
    """Env-backed retention schedule; dry-run is the safe default for jobs."""

    session_days: int = Field(default=30, ge=1, le=3650, validation_alias="RETENTION_SESSION_DAYS")
    memory_medium_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias="RETENTION_MEMORY_MEDIUM_DAYS",
    )
    memory_episode_days: int = Field(
        default=365,
        ge=1,
        le=3650,
        validation_alias="RETENTION_MEMORY_EPISODE_DAYS",
    )
    memory_pii_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias="RETENTION_MEMORY_PII_DAYS",
    )
    attachment_pii_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias="RETENTION_ATTACHMENT_PII_DAYS",
    )
    knowledge_orphan_days: int = Field(
        default=7,
        ge=1,
        le=3650,
        validation_alias="RETENTION_KNOWLEDGE_ORPHAN_DAYS",
    )
    graph_pii_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias="RETENTION_GRAPH_PII_DAYS",
    )
    audit_hot_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias="RETENTION_AUDIT_HOT_DAYS",
    )
    checkpoint_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias="RETENTION_CHECKPOINT_DAYS",
    )
    langfuse_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        validation_alias="RETENTION_LANGFUSE_DAYS",
    )
    # Align with existing MCP retention CLI defaults (handbook §15).
    mcp_archive_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        validation_alias="RETENTION_MCP_ARCHIVE_DAYS",
    )
    mcp_purge_years: int = Field(
        default=3,
        ge=1,
        le=50,
        validation_alias="RETENTION_MCP_PURGE_YEARS",
    )
    batch_size: int = Field(
        default=200,
        ge=1,
        le=5000,
        validation_alias="RETENTION_BATCH_SIZE",
    )
    anonymize_grace_days: int = Field(
        default=7,
        ge=0,
        le=90,
        validation_alias="RETENTION_ANONYMIZE_GRACE_DAYS",
    )
    execute: bool = Field(
        default=False,
        validation_alias="RETENTION_EXECUTE",
        description="Destructive job runs require true (or CLI --execute).",
    )
