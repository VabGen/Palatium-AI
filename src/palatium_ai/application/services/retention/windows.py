# src/palatium_ai/application/services/retention/windows.py

"""Map RetentionConfig → domain RetentionWindows (core must not import domain)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.policies.retention import RetentionWindows

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


def retention_windows_from_settings(settings: Settings) -> RetentionWindows:
    """Build frozen schedule from Settings.retention."""
    cfg = settings.retention
    return RetentionWindows(
        session_days=cfg.session_days,
        memory_medium_days=cfg.memory_medium_days,
        memory_episode_days=cfg.memory_episode_days,
        memory_pii_days=cfg.memory_pii_days,
        attachment_pii_days=cfg.attachment_pii_days,
        knowledge_orphan_days=cfg.knowledge_orphan_days,
        graph_pii_days=cfg.graph_pii_days,
        audit_hot_days=cfg.audit_hot_days,
        checkpoint_days=cfg.checkpoint_days,
        langfuse_days=cfg.langfuse_days,
        mcp_archive_days=cfg.mcp_archive_days,
        mcp_purge_years=cfg.mcp_purge_years,
        batch_size=cfg.batch_size,
        anonymize_grace_days=cfg.anonymize_grace_days,
    )
