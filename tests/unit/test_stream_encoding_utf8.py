"""UTF-8 must survive every hop, and the console stream must be forced to UTF-8.

The "mojibake in user_payload" symptom was not data corruption: the payload path is
``ensure_ascii=False`` JSON end to end. A piped stdio stream on a Russian Windows host
defaults to ``locale.getpreferredencoding()`` (cp1251/cp866), so a structlog event
written to it is emitted as legacy single-byte text and every UTF-8 reader renders
``покажи`` as ``РїРѕРєР°Р¶Рё``. ``reconfigure`` must pin the encoding, or the logs lie.
"""

from __future__ import annotations

import logging

from types import SimpleNamespace
from typing import TYPE_CHECKING

from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
from palatium_ai.application.agents.formatter.stream_delta import FormatterMarkdownEmitter
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.core.logging.setup import setup_logging

if TYPE_CHECKING:
    import pytest

RUSSIAN = "Покажи документ по договору №42 — заявка отклонена."
#: What a UTF-8 encoded Cyrillic answer looks like when a cp1251 console formats it.
LEGACY_CONSOLE_ARTIFACT = RUSSIAN[:1].encode().decode("cp1251")


class _FakeStream:
    """Minimal stdio double that records the ``reconfigure`` contract."""

    def __init__(self) -> None:
        self.reconfigure_kwargs: dict[str, object] | None = None
        self.written: list[str] = []

    def reconfigure(self, **kwargs: object) -> None:
        self.reconfigure_kwargs = kwargs

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _settings(**overrides: object) -> SimpleNamespace:
    log_cfg = {
        "json_logs": False,
        "level": "INFO",
        "file": None,
        "suppress_modules": "",
        "filter_modules": "",
    }
    log_cfg.update(overrides)
    return SimpleNamespace(
        logging=SimpleNamespace(**log_cfg),
        app=SimpleNamespace(name="palatium-ai", version="test", environment="test"),
    )


def test_console_streams_are_reconfigured_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout, stderr = _FakeStream(), _FakeStream()
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        setup_logging(_settings())
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

    for stream in (stdout, stderr):
        assert stream.reconfigure_kwargs is not None, "console stream left on the locale codec"
        assert stream.reconfigure_kwargs.get("encoding") == "utf-8"
        assert stream.reconfigure_kwargs.get("errors") == "replace"
        assert stream.reconfigure_kwargs.get("line_buffering") is True


def test_answer_delta_frames_carry_exact_cyrillic() -> None:
    bridge = TurnSseBridge()
    with turn_sse_bridge(bridge):
        emit_answer_deltas(RUSSIAN)

    painted = _painted(bridge)
    assert painted == RUSSIAN
    assert LEGACY_CONSOLE_ARTIFACT not in painted


def test_formatter_stream_frames_carry_exact_cyrillic() -> None:
    bridge = TurnSseBridge()
    emitter = FormatterMarkdownEmitter(bridge=bridge, replace_pending=False)
    for start in range(0, len(RUSSIAN), 5):
        emitter.on_delta(RUSSIAN[start : start + 5])
    emitter.finish()

    painted = _painted(bridge)
    assert painted == RUSSIAN
    assert LEGACY_CONSOLE_ARTIFACT not in painted


def _painted(bridge: TurnSseBridge) -> str:
    """Concatenate every painted frame (preview prefers ``text_delta``)."""
    events: list[dict[str, object]] = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    for name, key in (("text_delta", "content"), ("answer_delta", "delta")):
        joined = "".join(str(event.get(key) or "") for event in events if event.get("event") == name)
        if joined:
            return joined
    return ""
