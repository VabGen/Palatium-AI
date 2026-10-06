# src/palatium_ai/domain/policies/retention.py

"""Pure retention schedule: class → window → disposition (plans/global-retention)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.types import MemoryType

RetentionAction = Literal["delete", "archive", "anonymize", "report_only"]

RetentionClass = Literal[
    "session_transcript",
    "memory_medium",
    "memory_episode",
    "memory_pii",
    "attachment_attach",
    "attachment_index",
    "attachment_pii",
    "knowledge_orphan",
    "mcp_tool_call",
    "neo4j_memory_fact",
    "audit_chain",
    "checkpointer",
    "redis_ephemeral",
    "observability_ops",
    "observability_llm",
    "backup_snapshots",
    "processor_external",
    "report_only",
]

ALL_RETENTION_CLASSES: tuple[RetentionClass, ...] = (
    "session_transcript",
    "memory_medium",
    "memory_episode",
    "memory_pii",
    "attachment_attach",
    "attachment_index",
    "attachment_pii",
    "knowledge_orphan",
    "mcp_tool_call",
    "neo4j_memory_fact",
    "audit_chain",
    "checkpointer",
    "redis_ephemeral",
    "observability_ops",
    "observability_llm",
    "backup_snapshots",
    "processor_external",
    "report_only",
)


class RetentionWindows(BaseModel, frozen=True):
    """Numeric schedule injected from RetentionConfig (core → wiring → domain)."""

    session_days: int = Field(default=30, ge=1, le=3650)
    memory_medium_days: int = Field(default=30, ge=1, le=3650)
    memory_episode_days: int = Field(default=365, ge=1, le=3650)
    memory_pii_days: int = Field(default=90, ge=1, le=3650)
    attachment_pii_days: int = Field(default=90, ge=1, le=3650)
    knowledge_orphan_days: int = Field(default=7, ge=1, le=3650)
    graph_pii_days: int = Field(default=90, ge=1, le=3650)
    audit_hot_days: int = Field(default=90, ge=1, le=3650)
    checkpoint_days: int = Field(default=30, ge=1, le=3650)
    session_ttl_seconds: int = Field(default=1800, ge=60, le=30 * 24 * 3600)
    langfuse_days: int = Field(default=30, ge=1, le=3650)
    mcp_archive_days: int = Field(default=90, ge=1, le=3650)
    mcp_purge_years: int = Field(default=3, ge=1, le=50)
    batch_size: int = Field(default=200, ge=1, le=5000)
    anonymize_grace_days: int = Field(default=7, ge=0, le=90)


DEFAULT_RETENTION_WINDOWS = RetentionWindows()


class RetentionDecision(BaseModel, frozen=True):
    """Outcome of evaluating one candidate against policy."""

    retention_class: RetentionClass
    action: RetentionAction
    held: bool = False
    reason: str = ""


class RetentionPolicy:
    """Deterministic retention rules; clock injected (050)."""

    @staticmethod
    def effective_days(class_days: int, *, contains_pii: bool, pii_days: int) -> int:
        """PII never extends retention: min(class, pii) when flagged."""
        if class_days < 1 or pii_days < 1:
            msg = "retention days must be >= 1"
            raise ValueError(msg)
        if contains_pii:
            return min(class_days, pii_days)
        return class_days

    @staticmethod
    def memory_class(*, memory_type: MemoryType | str, contains_pii: bool) -> RetentionClass:
        """Map memory row axes to a retention class (PII wins)."""
        if contains_pii:
            return "memory_pii"
        if str(memory_type).strip().lower() == "episode":
            return "memory_episode"
        return "memory_medium"

    @staticmethod
    def memory_ttl_days(
        *,
        memory_type: MemoryType | str,
        contains_pii: bool,
        windows: RetentionWindows = DEFAULT_RETENTION_WINDOWS,
    ) -> int:
        """Days until medium-term memory row expires (access does not extend PII)."""
        kind = RetentionPolicy.memory_class(memory_type=memory_type, contains_pii=contains_pii)
        if kind == "memory_pii":
            base = (
                windows.memory_episode_days
                if str(memory_type).strip().lower() == "episode"
                else windows.memory_medium_days
            )
            return RetentionPolicy.effective_days(
                base,
                contains_pii=True,
                pii_days=windows.memory_pii_days,
            )
        if kind == "memory_episode":
            return windows.memory_episode_days
        return windows.memory_medium_days

    @staticmethod
    def memory_expires_at(
        *,
        memory_type: MemoryType | str,
        contains_pii: bool,
        created_at: datetime,
        windows: RetentionWindows = DEFAULT_RETENTION_WINDOWS,
    ) -> datetime:
        """Timezone-aware expiry from created_at + TTL (PII clock = created_at only)."""
        _require_aware(created_at)
        days = RetentionPolicy.memory_ttl_days(
            memory_type=memory_type,
            contains_pii=contains_pii,
            windows=windows,
        )
        return created_at + timedelta(days=days)

    @staticmethod
    def is_due(*, expires_at: datetime | None, now: datetime, held: bool = False) -> bool:
        """True when a row with expires_at may be reclaimed (hold vetoes)."""
        _require_aware(now)
        if held:
            return False
        if expires_at is None:
            return False
        aware = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
        return aware <= now

    @staticmethod
    def session_inactivity_cutoff(
        *,
        now: datetime,
        windows: RetentionWindows = DEFAULT_RETENTION_WINDOWS,
    ) -> datetime:
        """Sessions with updated_at strictly before this UTC instant are reclaimable."""
        _require_aware(now)
        return now - timedelta(days=windows.session_days)

    @staticmethod
    def checkpoint_inactivity_cutoff(
        *,
        now: datetime,
        windows: RetentionWindows = DEFAULT_RETENTION_WINDOWS,
    ) -> datetime:
        """Dual TTL: earlier of hot ``session_ttl_seconds`` and cold ``checkpoint_days``.

        Sessions with ``updated_at`` strictly before this UTC instant are reclaimable
        (inactive > hot **or** age > cold — equivalent to ``now - min(hot, cold)``).

        Reclaim runs on the retention CronJob cadence (ADR 0002), not as a native
        EXPIRE at ``T+session_ttl``; document ops accordingly (ADR 0003).
        """
        _require_aware(now)
        hot = timedelta(seconds=windows.session_ttl_seconds)
        cold = timedelta(days=windows.checkpoint_days)
        return now - min(hot, cold)

    @staticmethod
    def decide(
        retention_class: RetentionClass,
        *,
        held: bool = False,
        anonymized: bool = False,
    ) -> RetentionDecision:
        """Default disposition for a class (execute path still re-checks hold)."""
        if held:
            return RetentionDecision(
                retention_class=retention_class,
                action="report_only",
                held=True,
                reason="legal_hold",
            )
        if retention_class == "report_only":
            return RetentionDecision(retention_class=retention_class, action="report_only", reason="noop")
        if retention_class in {"audit_chain", "backup_snapshots", "processor_external"}:
            return RetentionDecision(
                retention_class=retention_class,
                action="report_only",
                reason="ops_documented_rotation",
            )
        if retention_class in {"memory_pii", "attachment_pii", "neo4j_memory_fact"} and not anonymized:
            return RetentionDecision(
                retention_class=retention_class,
                action="anonymize",
                reason="pii_then_grace_delete",
            )
        if retention_class == "mcp_tool_call":
            return RetentionDecision(
                retention_class=retention_class,
                action="archive",
                reason="archive_then_purge",
            )
        if retention_class in {
            "redis_ephemeral",
            "observability_ops",
            "observability_llm",
        }:
            return RetentionDecision(
                retention_class=retention_class,
                action="report_only",
                reason="platform_native_ttl",
            )
        return RetentionDecision(retention_class=retention_class, action="delete", reason="ttl_elapsed")

    @staticmethod
    def resolve_conflict_days(*windows: int) -> int:
        """When obligations overlap and selective purge is impossible: keep longest."""
        if not windows:
            msg = "at least one window required"
            raise ValueError(msg)
        if any(day < 1 for day in windows):
            msg = "retention days must be >= 1"
            raise ValueError(msg)
        return max(windows)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "retention datetime must be timezone-aware (UTC)"
        raise ValueError(msg)
