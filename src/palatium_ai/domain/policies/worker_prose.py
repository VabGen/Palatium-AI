# src/palatium_ai/domain/policies/worker_prose.py

"""Keep structured worker envelopes out of user-visible prose (2026 JSON-bleed).

Researcher / worker LLMs return ``{"summary": "...", "confidence": …}``. When the
codec cannot load the object (raw newlines, truncated braces, nested quotes), a
naïve freeform fallback used to ship the **wire format** to the client. Best
practice 2026: parse/validate the envelope server-side; render only the
user-facing field; never stream raw JSON (Bibra / structured-output production
guides; “JSON bleed” class).

Structural only (055): the contract field name is ``summary`` (ResearcherOutput),
not a language phrase list.
"""

from __future__ import annotations

import re

from palatium_ai.domain.llm.json_codec import LLMJSONError, loads_llm_json

#: Researcher / worker user-visible field (domain contract — single name).
_SUMMARY_FIELD = "summary"
_SUMMARY_KEY = re.compile(r'"summary"\s*:', re.IGNORECASE)


class WorkerProsePolicy:
    """Pure policy: unwrap structured envelopes before user-facing emit."""

    @classmethod
    def user_visible(cls, text: str) -> str:
        """Return prose safe to paint; lift ``summary`` when ``text`` is an envelope."""
        raw = (text or "").strip()
        if not raw:
            return text
        lifted = cls.lift_summary_envelope(raw)
        return lifted if lifted is not None else text

    @classmethod
    def lift_summary_envelope(cls, text: str) -> str | None:
        """If ``text`` is a worker JSON envelope, return the ``summary`` string.

        Returns ``None`` when the text is ordinary prose (no envelope). Nested
        envelopes (summary value is itself a JSON object string with ``summary``)
        are unwrapped once. A leading prose prefix (disclaimer / assumption mark)
        is skipped so unwrap still works after those layers.
        """
        stripped = (text or "").strip()
        if _SUMMARY_KEY.search(stripped) is None:
            return None
        candidates: list[str] = []
        if stripped.startswith("{"):
            candidates.append(stripped)
        brace = stripped.find("{")
        if brace > 0:
            candidates.append(stripped[brace:])

        for candidate in candidates:
            payload = cls._loads_object(candidate)
            if payload is not None:
                summary = cls._summary_from_mapping(payload)
                if summary is not None:
                    return cls._unwrap_nested_summary(summary)
            extracted = cls._extract_string_field(candidate, _SUMMARY_FIELD)
            if extracted is not None:
                return cls._unwrap_nested_summary(extracted)
        return None

    @classmethod
    def _loads_object(cls, text: str) -> dict[str, object] | None:
        try:
            payload = loads_llm_json(text)
        except LLMJSONError:
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _summary_from_mapping(cls, payload: dict[str, object]) -> str | None:
        raw = payload.get(_SUMMARY_FIELD)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    @classmethod
    def _unwrap_nested_summary(cls, summary: str) -> str:
        """One-level nested envelope: summary value is a JSON object string."""
        inner = summary.strip()
        if not inner.startswith("{") or _SUMMARY_KEY.search(inner) is None:
            return summary
        payload = cls._loads_object(inner)
        if payload is None:
            return summary
        nested = cls._summary_from_mapping(payload)
        return nested if nested is not None else summary

    @classmethod
    def _extract_string_field(cls, text: str, field: str) -> str | None:
        """Pull a JSON string field even when the surrounding object is broken.

        Escape-aware scan from the first ``"field": "…`` occurrence — last resort
        after the codec ladder failed (truncated outer braces, etc.).
        """
        needle = f'"{field}"'
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx < 0:
                return None
            colon = text.find(":", idx + len(needle))
            if colon < 0:
                return None
            i = colon + 1
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i >= len(text) or text[i] != '"':
                start = idx + len(needle)
                continue
            return cls._scan_json_string(text, i + 1)

    @staticmethod
    def _scan_json_string(text: str, begin: int) -> str | None:
        out: list[str] = []
        escape = False
        i = begin
        while i < len(text):
            ch = text[i]
            if escape:
                decoded, consumed = _decode_json_escape(text, i)
                out.append(decoded)
                i += consumed
                escape = False
                continue
            if ch == "\\":
                escape = True
                i += 1
                continue
            if ch == '"':
                return "".join(out)
            out.append(ch)
            i += 1
        # Unclosed string: return what we have if non-empty (truncated stream).
        recovered = "".join(out).strip()
        return recovered or None


def _decode_json_escape(text: str, index: int) -> tuple[str, int]:
    """Decode one JSON escape at ``index``; return ``(char, chars_consumed)``."""
    ch = text[index]
    if ch == "n":
        return "\n", 1
    if ch == "t":
        return "\t", 1
    if ch == "r":
        return "\r", 1
    if ch in {'"', "\\", "/"}:
        return ch, 1
    if ch == "u" and index + 4 < len(text):
        hex_digits = text[index + 1 : index + 5]
        try:
            return chr(int(hex_digits, 16)), 5
        except ValueError:
            return ch, 1
    return ch, 1


__all__ = ["WorkerProsePolicy"]
