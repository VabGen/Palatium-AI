"""ClamAV adapter: INSTREAM framing, reply parsing, fail-closed verdicts (020, 050)."""

from __future__ import annotations

import socket
import threading

import pytest

from palatium_ai.infrastructure.scanning.clamav_adapter import (
    ClamAVScanner,
    build_instream_body,
    parse_clamd_reply,
)


def test_instream_body_is_length_prefixed_and_terminated() -> None:
    """clamd expects zINSTREAM\\0, 4-byte big-endian chunk lengths, then a zero chunk."""
    body = build_instream_body(b"abc")
    assert body.startswith(b"zINSTREAM\x00")
    assert body[10:14] == b"\x00\x00\x00\x03"
    assert body[14:17] == b"abc"
    assert body.endswith(b"\x00\x00\x00\x00")


def test_instream_body_chunks_large_payloads() -> None:
    """A 64 KiB chunk boundary keeps the length prefixes honest."""
    payload = b"x" * (65_536 + 5)
    body = build_instream_body(payload)
    assert body[10:14] == b"\x00\x01\x00\x00"  # first chunk: 65536
    assert body.endswith(b"\x00\x00\x00\x05" + b"xxxxx" + b"\x00\x00\x00\x00")  # tail: 5
    assert body.count(b"x") == len(payload)


def test_empty_payload_still_produces_a_terminated_stream() -> None:
    assert build_instream_body(b"") == b"zINSTREAM\x00\x00\x00\x00\x00"


def test_clean_reply_is_clean() -> None:
    verdict = parse_clamd_reply(b"stream: OK\x00", scanned_bytes=10)
    assert verdict.clean
    assert not verdict.failed
    assert verdict.engine == "clamav"
    assert verdict.scanned_bytes == 10


def test_infected_reply_exposes_the_signature() -> None:
    verdict = parse_clamd_reply(b"stream: Eicar-Signature FOUND\x00", scanned_bytes=68)
    assert not verdict.clean
    assert verdict.infected
    assert not verdict.failed
    assert verdict.signature == "Eicar-Signature"


def test_signature_ending_in_ok_is_not_treated_as_clean() -> None:
    """Regression: 'FOUND' must be tested before the 'OK' suffix check."""
    verdict = parse_clamd_reply(b"stream: Trojan.Some.Ok FOUND\x00")
    assert not verdict.clean
    assert verdict.infected


def test_engine_error_fails_closed_and_is_marked_failed() -> None:
    """An unintelligible reply must not admit the payload (020)."""
    verdict = parse_clamd_reply(b"INSTREAM size limit exceeded. ERROR\x00")
    assert not verdict.clean
    assert verdict.failed
    assert not verdict.infected
    # ``infected`` is only evidence of malice; ``admitted`` is the gate callers use,
    # and it stays False for an engine failure (020: no fail-open on AV errors).
    assert not verdict.admitted


def test_only_a_clean_verdict_is_admitted() -> None:
    """Regression: branching on ``infected`` would admit unscanned content."""
    assert parse_clamd_reply(b"stream: OK\x00").admitted
    assert not parse_clamd_reply(b"stream: Eicar-Signature FOUND\x00").admitted
    assert not parse_clamd_reply(b"INSTREAM size limit exceeded. ERROR\x00").admitted


def test_empty_reply_fails_closed() -> None:
    verdict = parse_clamd_reply(b"")
    assert not verdict.clean
    assert verdict.failed


@pytest.mark.asyncio()
async def test_unreachable_daemon_returns_failed_verdict_instead_of_raising() -> None:
    """A scanner outage is a quarantine signal, never an exception at the call site."""
    scanner = ClamAVScanner(host="127.0.0.1", port=1, timeout_seconds=0.5)
    verdict = await scanner.scan(b"payload", filename="a.txt")
    assert not verdict.clean
    assert verdict.failed
    assert verdict.reason is not None
    assert verdict.reason.startswith("clamd unreachable")
    assert verdict.scanned_bytes == 7


@pytest.mark.asyncio()
async def test_socket_io_runs_off_the_event_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for 050: the socket service has no asyncio driver."""
    observed: dict[str, int] = {}

    class _FakeSocket:
        def __enter__(self) -> _FakeSocket:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def settimeout(self, _timeout: float) -> None:
            return None

        def sendall(self, _payload: bytes) -> None:
            return None

        def recv(self, _size: int) -> bytes:
            observed["thread"] = threading.get_ident()
            return b"stream: OK\x00"

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: _FakeSocket())
    scanner = ClamAVScanner(host="clamd", port=3310)
    verdict = await scanner.scan(b"payload", filename="a.txt")

    assert verdict.clean
    assert observed["thread"] != threading.get_ident()
