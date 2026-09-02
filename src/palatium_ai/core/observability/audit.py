# src/palatium_ai/core/observability/audit.py

"""Hash-chained audit logging (append-only)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Final

from pydantic import BaseModel, Field

from palatium_ai.core.exceptions import AuditChainIntegrityError, AuditWriteDegradedError

logger = logging.getLogger(__name__)

@dataclass
class _ChainRecord:
    """Parsed and validated record from one audit log line."""

    line_no: int
    ts: str
    conv: str
    ev: str
    current: str
    meta: dict[str, str]
    previous: str | None = None
    stored_mac: str | None = None


GENESIS_HASH: Final[str] = "genesis"

# Размер хвостового чтения: с запасом, чтобы граница не разрывала
# UTF-8-символ в кириллических metadata (ensure_ascii=False).
_TAIL_BLOCK_SIZE: Final[int] = 8192

# Dead-letter файл для событий, не попавших в chain при OSError.
_DEAD_LETTER_SUFFIX: Final[str] = ".dead-letter.log"

_SINGLETON_LOCK = Lock()

_AUDIT_WRITE_FAILURES_TOTAL = 0  # простая метрика; заменить на метрики


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
    container_logs = Path("/app/logs")
    if container_logs.is_dir() or Path("/app").is_dir():
        return container_logs / "audit-chain.log"

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / ".cursor" / "logs" / "audit-chain.log"

    return Path.cwd() / "logs" / "audit-chain.log"


def _audit_hmac_secret() -> str | None:
    raw = os.getenv("AUDIT_HMAC_SECRET", "").strip()
    return raw or None


def _normalize_timestamp(raw: str) -> str:
    """Нормализует timestamp к единому формату ``YYYY-MM-DDTHH:MM:SSZ``.

    Продов bug: смесь ``+00:00`` и ``Z`` ломает парсинг downstream.
    Единая точка нормализации убирает класс ошибок целиком.
    """
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("audit timestamp is not ISO-8601: %r", raw[:64])
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(slots=True)
class AuditChainLogger:
    """Append-only audit writer with sha256 hash chaining.

    Invariants
    ----------
    - Single-writer: ровно один процесс на file_path. threading.Lock
      защищает только потоки внутри процесса; межпроцессная конкуренция
      порождает развилки цепочки и молча теряет tamper-evidence.
      При масштабировании >1 worker — вынести chain в БД с row-lock.
    - Отказ записи (OSError) НЕ прерывает бизнес-флоу: событие уходит в
      dead-letter файл, инкрементируется счётчик, вызывающему возвращается
      AuditWriteDegradedError. Повреждение существующей цепочки — fail loud
      (AuditChainIntegrityError): это сигнал о tamper или corruption.
    """

    file_path: Path
    hmac_secret: str | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def _read_last_current_hash(self) -> str:
        """Читает current_hash последней валидной записи хвоста файла.

        Хвост читается блоком и декодируется с обрезкой по границе строк:
        UTF-8-символ в середине блока больше не роняет чтение, а
        недописанная последняя строка (crash mid-write) отбрасывается.
        """
        if not self.file_path.exists():
            return GENESIS_HASH

        try:
            with self.file_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    return GENESIS_HASH
                start = max(size - _TAIL_BLOCK_SIZE, 0)
                f.seek(start)
                raw_tail = f.read()
        except OSError as exc:
            raise AuditChainIntegrityError(f"Unable to read audit chain at {self.file_path}: {exc}") from exc

        text = raw_tail.decode("utf-8", errors="ignore")
        lines = [line for line in text.splitlines() if line.strip()]
        if start > 0 and not text.endswith("\n") and lines:
            lines = lines[:-1]
        if not lines:
            return GENESIS_HASH

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

    @staticmethod
    def _canonical_payload(
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str],
    ) -> dict[str, object]:
        """Канонический payload для hashing.

        Единственный источник истины для append() и verify_chain().
        Metadata опускается, когда пустая — оба метода обязаны
        согласованно использовать этот метод, иначе верификация молча
        разойдётся с записью.
        """
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "conversation_id": conversation_id,
            "event": event,
        }
        if metadata:
            payload["metadata"] = metadata
        return payload

    def _compute_current_hash(self, previous_hash: str, payload: dict[str, object]) -> str:
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        )
        return hashlib.sha256(f"{previous_hash}{payload_json}".encode()).hexdigest()

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
        meta = dict(metadata or {})
        normalized_ts = _normalize_timestamp(timestamp)

        with self._lock:
            previous_hash = self._read_last_current_hash()
            payload = self._canonical_payload(
                timestamp=normalized_ts,
                conversation_id=conversation_id,
                event=event,
                metadata=meta,
            )
            current_hash = self._compute_current_hash(previous_hash, payload)
            integrity_mac = self._compute_integrity_mac(current_hash)
            record = AuditRecord(
                timestamp=normalized_ts,
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
                f.flush()
                # os.fsync(f.fileno()) — раскомментировать, если аудит
                # является комплаенс-требованием (цена: latency per record)

            return record

    async def append_async(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None = None,
    ) -> AuditRecord:
        """Асинхронная обёртка над append().

        Контракт ошибок:
        - AuditChainIntegrityError → пробрасывается (fail loud):
          повреждение существующей цепочки — сигнал tamper/corruption.
        - AuditWriteDegradedError → пробрасывается, но бизнес-флоу обязан его
          проглотить и продолжить: отказ диска не должен ронять
          пользовательский сценарий (см. ResearcherAgent).
        """
        try:
            return await asyncio.to_thread(
                self.append,
                timestamp=timestamp,
                conversation_id=conversation_id,
                event=event,
                metadata=metadata,
            )
        except AuditChainIntegrityError:
            raise
        except OSError:
            global _AUDIT_WRITE_FAILURES_TOTAL
            _AUDIT_WRITE_FAILURES_TOTAL += 1
            logger.exception(
                "audit append failed (chain degraded), event=%s conv=%s",
                event,
                conversation_id,
            )
            await asyncio.to_thread(
                self._write_dead_letter,
                timestamp=timestamp,
                conversation_id=conversation_id,
                event=event,
                metadata=metadata,
            )
            raise AuditWriteDegradedError(
                f"Audit chain write failed for event={event!r}; event preserved in dead-letter"
            ) from None

    def _write_dead_letter(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None,
    ) -> None:
        """Сохраняет событие вне цепочки — best effort, без raise."""
        try:
            dead_letter_path = self.file_path.with_suffix(_DEAD_LETTER_SUFFIX)
            dead_letter_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "event": event,
                "metadata": metadata or {},
                "reason": "chain_write_failed",
            }
            with dead_letter_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False))
                f.write("\n")
        except OSError:
            # dead-letter тоже недоступен — остаётся только лог
            logger.critical(
                "audit dead-letter write ALSO failed; event lost from disk: event=%s conv=%s meta=%s",
                event,
                conversation_id,
                metadata,
            )

    def verify_chain(self, *, limit: int | None = None) -> list[str]:
        """Проверяет целостность цепочки; возвращает список ошибок.

        Пустой список = chain валиден от genesis (или от начала файла,
        если он был ротирован — тогда first-line chain break ожидаем).

        Использует тот же _canonical_payload, что и append() — расхождение
        невозможно по построению.
        """
        errors: list[str] = []
        if not self.file_path.exists():
            return errors

        previous = GENESIS_HASH
        with self.file_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if limit is not None and line_no > limit:
                    break
                rec = self._parse_record(line_no, line, errors)
                if rec is None:
                    continue
                errors.extend(self._check_chain_link(rec, previous))
                previous = rec.current
        return errors

    def _parse_record(self, line_no: int, line: str, errors: list[str]) -> _ChainRecord | None:
        """Parse and validate one audit log line, appending errors to the list."""
        line = line.strip()
        if not line:
            return None
        try:
            rec: object = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {line_no}: not valid JSON")
            return None
        if not isinstance(rec, dict):
            errors.append(f"line {line_no}: record is not an object")
            return None

        ts = rec.get("timestamp")
        conv = rec.get("conversation_id")
        ev = rec.get("event")
        current = rec.get("current_hash")
        meta = rec.get("metadata", {})
        if not all(isinstance(v, str) for v in (ts, conv, ev, current)):
            errors.append(f"line {line_no}: missing required fields")
            return None
        if not isinstance(meta, dict):
            errors.append(f"line {line_no}: metadata is not an object")
            return None

        return _ChainRecord(
            line_no=line_no,
            ts=ts,
            conv=conv,
            ev=ev,
            current=current,
            meta={str(k): str(v) for k, v in meta.items()},
            previous=rec.get("previous_hash"),
            stored_mac=rec.get("integrity_mac"),
        )

    def _check_chain_link(self, rec: _ChainRecord, previous_hash: str) -> list[str]:
        """Verify hash chain continuity and integrity MAC for one record."""
        part_errors: list[str] = []
        ln = rec.line_no

        if rec.previous != previous_hash:
            part_errors.append(f"line {ln}: chain break")

        payload = self._canonical_payload(
            timestamp=rec.ts,
            conversation_id=rec.conv,
            event=rec.ev,
            metadata=rec.meta,
        )
        expected = self._compute_current_hash(previous_hash, payload)
        if rec.current != expected:
            part_errors.append(f"line {ln}: hash mismatch")

        if self.hmac_secret and isinstance(rec.stored_mac, str):
            computed_mac = self._compute_integrity_mac(rec.current) or ""
            if not hmac.compare_digest(rec.stored_mac, computed_mac):
                part_errors.append(f"line {ln}: MAC mismatch")

        return part_errors


_LOGGER: AuditChainLogger | None = None


def get_audit_logger() -> AuditChainLogger:
    """Singleton writer (потокобезопасное создание).

    Два конкурентных инстанса = две развилки цепочки, поэтому создание
    защищено lock'ом, а не только check-then-act.
    """
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    with _SINGLETON_LOCK:
        if _LOGGER is not None:
            return _LOGGER
        env_path = os.getenv("AUDIT_LOG_FILE")
        file_path = Path(env_path) if env_path else _default_audit_log_path()
        _LOGGER = AuditChainLogger(file_path=file_path, hmac_secret=_audit_hmac_secret())
        return _LOGGER


def reset_audit_logger_for_tests() -> None:
    """Clear singleton (unit tests only)."""
    global _LOGGER
    with _SINGLETON_LOCK:
        _LOGGER = None
