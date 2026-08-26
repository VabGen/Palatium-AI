# src/palatium_ai/core/observability/audit.py

"""Hash-chained audit logging (append-only)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Final

from pydantic import BaseModel, Field

from palatium_ai.core.exceptions import AuditChainIntegrityError


class AuditRecord(BaseModel):
    """Запись аудит-цепочки (tamper-evident)."""

    model_config = {"frozen": True}

    timestamp: str
    conversation_id: str
    event: str
    previous_hash: str
    current_hash: str
    metadata: dict[str, str] = Field(default_factory=dict)
    integrity_mac: str | None = None


def _default_audit_log_path() -> Path:
    """Путь к hash-chained audit log (writable и в Docker, и локально)."""
    # Контейнер: /app/logs (compose tmpfs / volume)
    container_logs = Path("/app/logs")
    if container_logs.is_dir() or Path("/app").is_dir():
        return container_logs / "audit-chain.log"

    # Dev: корень репозитория → .cursor/logs (как session-audit-log hook)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / ".cursor" / "logs" / "audit-chain.log"

    return Path.cwd() / "logs" / "audit-chain.log"


def _audit_hmac_secret() -> str | None:
    raw = os.getenv("AUDIT_HMAC_SECRET", "").strip()
    return raw or None


@dataclass(slots=True)
class AuditChainLogger:
    """Append-only audit writer with sha256 hash chaining."""

    file_path: Path
    hmac_secret: str | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    _GENESIS_HASH: Final[str] = "genesis"

    def _read_last_current_hash(self) -> str:
        if not self.file_path.exists():
            return self._GENESIS_HASH

        try:
            with self.file_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return self._GENESIS_HASH
                block_size = 4096
                f.seek(max(f.tell() - block_size, 0))
                data = f.read().decode("utf-8", errors="strict")
        except OSError as exc:
            raise AuditChainIntegrityError(f"Unable to read audit chain at {self.file_path}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise AuditChainIntegrityError(f"Corrupt audit chain encoding at {self.file_path}") from exc

        lines = [line for line in data.splitlines() if line.strip()]
        if not lines:
            return self._GENESIS_HASH
        last = lines[-1]
        try:
            record = json.loads(last)
        except json.JSONDecodeError as exc:
            raise AuditChainIntegrityError(f"Corrupt audit chain JSON at {self.file_path}") from exc
        if not isinstance(record, dict):
            raise AuditChainIntegrityError(f"Corrupt audit chain record shape at {self.file_path}")
        current = record.get("current_hash")
        if not isinstance(current, str) or not current.strip():
            raise AuditChainIntegrityError(f"Missing current_hash in last audit record at {self.file_path}")
        return current

    def _compute_current_hash(self, previous_hash: str, payload: dict[str, object]) -> str:
        # Важно: без sort_keys, чтобы порядок полей был детерминированным по insertion order.
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        )
        digest = hashlib.sha256(f"{previous_hash}{payload_json}".encode()).hexdigest()
        return digest

    def _compute_integrity_mac(self, current_hash: str) -> str | None:
        if not self.hmac_secret:
            return None
        return hmac.new(
            self.hmac_secret.encode("utf-8"),
            current_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def append(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None = None,
    ) -> AuditRecord:
        """Записывает запись в файл синхронно."""
        meta = metadata or {}

        with self._lock:
            previous_hash = self._read_last_current_hash()
            payload: dict[str, object] = {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "event": event,
            }
            if meta:
                payload["metadata"] = meta

            current_hash = self._compute_current_hash(previous_hash, payload)
            integrity_mac = self._compute_integrity_mac(current_hash)
            record = AuditRecord(
                timestamp=timestamp,
                conversation_id=conversation_id,
                event=event,
                previous_hash=previous_hash,
                current_hash=current_hash,
                metadata=meta,
                integrity_mac=integrity_mac,
            )

            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(record.model_dump_json(ensure_ascii=False, exclude_none=True))
                f.write("\n")

            return record

    async def append_async(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None = None,
    ) -> AuditRecord:
        """Асинхронная обёртка над append()."""
        return await asyncio.to_thread(
            self.append,
            timestamp=timestamp,
            conversation_id=conversation_id,
            event=event,
            metadata=metadata,
        )


_LOGGER: AuditChainLogger | None = None


def get_audit_logger() -> AuditChainLogger:
    """Singleton writer."""
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    env_path = os.getenv("AUDIT_LOG_FILE")
    file_path = Path(env_path) if env_path else _default_audit_log_path()
    _LOGGER = AuditChainLogger(file_path=file_path, hmac_secret=_audit_hmac_secret())
    return _LOGGER


def reset_audit_logger_for_tests() -> None:
    """Clear singleton (unit tests only)."""
    global _LOGGER
    _LOGGER = None
