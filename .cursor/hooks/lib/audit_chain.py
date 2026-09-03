#!/usr/bin/env python
"""lib/audit_chain.py — hash-chained запись в audit-chain.log без jq/fcntl.

Формула идентична lib/audit-chain.sh (единственный источник истины на два
рантайма, оба реализуют один и тот же контракт — намеренное дублирование
формулы между bash/python, но НЕ дублирование самой логики хука, 050):

    current_hash = sha256(previous_hash + sha256(canonical_json(payload)))

Блокировка — через lock-файл (os.O_CREAT | os.O_EXCL), а не fcntl.flock,
чтобы работать на Windows без дополнительных зависимостей.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time

from datetime import UTC, datetime
from pathlib import Path

try:
    import fcntl  # POSIX only — недоступен на Windows

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — Windows
    _HAS_FCNTL = False

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "audit-chain.log"
# ВАЖНО: на POSIX это ТОТ ЖЕ файл, что flock'ает lib/audit-chain.sh (bash).
# Раньше здесь была отдельная O_EXCL-блокировка на этом же пути — bash
# никогда не удаляет свой лок-файл после flock (это штатно для flock:
# удаление лок-файла — источник гонок), а python видел "файл существует"
# и считал его вечно занятым. Итог: deny-dangerous-shell.py ни разу не мог
# записать в цепочку, если рядом отрабатывал любой bash-хук. Фикс — тот же
# flock() syscall на тот же файл, а не своя схема поверх чужой.
_LOCK_FILE_POSIX = _LOG_DIR / ".audit-chain.lock"
# На Windows (нет fcntl) bash-хуки в любом случае не выполняются нативно —
# отдельное имя специально, чтобы не путать два несовместимых механизма.
_LOCK_FILE_WINDOWS = _LOG_DIR / ".audit-chain.lock.win"
_LOCK_TIMEOUT_SEC = 5.0
_LOCK_POLL_SEC = 0.05


class _FileLock:
    """Exclusive lock: flock() на POSIX (совместим с lib/audit-chain.sh).

    O_EXCL-мьютекс на Windows (fcntl недоступен).
    """

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._fh: object | None = None
        self._excl_path: Path | None = None

    def __enter__(self) -> _FileLock:
        if _HAS_FCNTL:
            self._fh = open(_LOCK_FILE_POSIX, "a")
            deadline = time.monotonic() + self._timeout
            while True:
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
                    return self
                except BlockingIOError as err:
                    if time.monotonic() >= deadline:
                        self._fh.close()
                        raise TimeoutError(f"audit-chain: flock {_LOCK_FILE_POSIX} занят > {self._timeout}s") from err
                    time.sleep(_LOCK_POLL_SEC)

        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(str(_LOCK_FILE_WINDOWS), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self._excl_path = _LOCK_FILE_WINDOWS
                return self
            except FileExistsError as err:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"audit-chain: lock {_LOCK_FILE_WINDOWS} занят > {self._timeout}s") from err
                time.sleep(_LOCK_POLL_SEC)

    def __exit__(self, *exc: object) -> None:
        if _HAS_FCNTL and self._fh is not None:
            fcntl.flock(self._fh, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            self._fh.close()
            # Файл НЕ удаляем — та же причина, что и в bash-версии: удаление
            # лок-файла между unlock и следующим open() создаёт гонку.
            return
        if self._excl_path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self._excl_path)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_event(event_type: str, extra: dict[str, object] | None = None) -> None:
    """Дописывает событие в hash-chained audit-chain.log.

    Никогда не бросает наружу (вызывающий хук не должен падать из-за сбоя
    аудита) — при ошибке пишет в stderr и молча возвращает управление.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.touch(exist_ok=True)

        with _FileLock(_LOCK_TIMEOUT_SEC):
            prev_hash = "genesis"
            lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
            if lines:
                last_line = lines[-1]
                try:
                    prev_hash = json.loads(last_line)["current_hash"]
                except Exception:  # noqa: BLE001 — повреждённая строка, не genesis
                    prev_hash = "CHAIN-CORRUPTED-" + _sha256(last_line)
                    print(
                        f"🚨 audit-chain: последняя запись в {_LOG_FILE} не парсится — "
                        "цепочка помечена как CORRUPTED, не сброшена в genesis",
                        file=__import__("sys").stderr,
                    )

            timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = {"timestamp": timestamp, "event": event_type, **(extra or {})}
            canonical_payload = _canonical_json(payload)
            inner_hash = _sha256(canonical_payload)
            current_hash = _sha256(prev_hash + inner_hash)

            record = {**payload, "previous_hash": prev_hash, "current_hash": current_hash}
            with _LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(_canonical_json(record) + "\n")
    except Exception as exc:  # noqa: BLE001
        import sys

        print(f"⚠️  audit-chain: событие {event_type} НЕ записано ({type(exc).__name__}: {exc})", file=sys.stderr)
