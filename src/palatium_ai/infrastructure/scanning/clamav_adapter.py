# src/palatium_ai/infrastructure/scanning/clamav_adapter.py

"""ClamAV ``MalwareScannerPort`` over clamd's native INSTREAM protocol.

Speaks the stream protocol directly over a socket instead of pulling in the
``clamd`` client: that package is unmaintained and uses blocking sockets anyway,
so a ~30 line protocol implementation removes a supply-chain dependency and one
abstraction that would have to be re-verified. All socket I/O runs in a worker
thread (050) — the socket service also has no asyncio driver.

Error semantics (020, fail closed): an unreachable, slow, or unintelligible clamd
is reported as ``clean=False, failed=True``. ``failed`` is a distinct field so
audit can tell "malware found" from "engine could not answer" — but neither
admits the payload.
"""

from __future__ import annotations

import asyncio
import socket

from palatium_ai.domain.ports.scanner import ScanVerdict

_INSTREAM_COMMAND = b"zINSTREAM\0"
_STREAM_TERMINATOR = b"\x00\x00\x00\x00"
_CHUNK_SIZE = 64 * 1024
_MAX_REPLY_BYTES = 4096
_ENGINE = "clamav"


def build_instream_body(data: bytes) -> bytes:
    """Frame ``data`` as a clamd INSTREAM request (length-prefixed chunks + terminator)."""
    parts: list[bytes] = [_INSTREAM_COMMAND]
    for offset in range(0, len(data), _CHUNK_SIZE):
        chunk = data[offset : offset + _CHUNK_SIZE]
        parts.append(len(chunk).to_bytes(4, "big"))
        parts.append(chunk)
    parts.append(_STREAM_TERMINATOR)
    return b"".join(parts)


def parse_clamd_reply(raw: bytes, *, scanned_bytes: int = 0) -> ScanVerdict:
    """Turn a raw clamd reply into a verdict, failing closed on anything unexpected.

    ``FOUND`` is tested before ``OK`` because a signature name may itself end in
    ``ok``; treating that as clean would be a silent false negative.
    """
    text = raw.decode("utf-8", errors="replace").strip("\x00 \t\r\n")
    if not text:
        return ScanVerdict(
            clean=False,
            engine=_ENGINE,
            failed=True,
            reason="empty reply from clamd",
            scanned_bytes=scanned_bytes,
        )
    lowered = text.lower()
    if lowered.endswith("found"):
        signature = text.split(":", 1)[-1]
        signature = signature[: -len("found")].strip() or "unknown"
        return ScanVerdict(
            clean=False,
            engine=_ENGINE,
            reason="malware signature matched",
            signature=signature[:256],
            scanned_bytes=scanned_bytes,
        )
    if lowered.endswith(": ok"):
        return ScanVerdict(clean=True, engine=_ENGINE, scanned_bytes=scanned_bytes)
    return ScanVerdict(
        clean=False,
        engine=_ENGINE,
        failed=True,
        reason=text[:_MAX_REPLY_BYTES],
        scanned_bytes=scanned_bytes,
    )


class ClamAVScanner:
    """MalwareScannerPort backed by a clamd daemon."""

    def __init__(self, *, host: str, port: int = 3310, timeout_seconds: float = 30.0) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    async def scan(self, data: bytes, *, filename: str) -> ScanVerdict:
        """Scan bytes; never raises for an engine problem, always returns a verdict."""
        try:
            raw = await asyncio.to_thread(self._scan_sync, data)
        except (OSError, TimeoutError) as exc:
            return ScanVerdict(
                clean=False,
                engine=_ENGINE,
                failed=True,
                reason=f"clamd unreachable: {type(exc).__name__}",
                scanned_bytes=len(data),
            )
        return parse_clamd_reply(raw, scanned_bytes=len(data))

    def _scan_sync(self, data: bytes) -> bytes:
        with socket.create_connection((self._host, self._port), timeout=self._timeout_seconds) as sock:
            sock.settimeout(self._timeout_seconds)
            sock.sendall(build_instream_body(data))
            return self._read_reply(sock)

    @staticmethod
    def _read_reply(sock: socket.socket) -> bytes:
        """Read until clamd's NUL terminator (or the safety cap) is reached."""
        chunks: list[bytes] = []
        total = 0
        while total < _MAX_REPLY_BYTES:
            chunk = sock.recv(_MAX_REPLY_BYTES - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if b"\0" in chunk or b"\n" in chunk:
                break
        return b"".join(chunks)
