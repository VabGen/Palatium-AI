# palatium_ai/domain/llm/json_codec.py

"""Parse JSON objects/arrays from LLM text (fences, trailing commas, raw control characters, unescaped inner quotes).

Design
------
:class:`JSONCodec` is an instantiable, dependency-injected parser:

* no module-level mutable state — the telemetry hook lives on the instance;
* the repair ladder is a declarative tuple of pure strategies
  (Open/Closed: add a strategy, do not touch ``loads``);
* deterministic repairs run first, heuristic full-repair via
  ``json_repair`` runs last and requires the optional extra dependency;
* every successful non-trivial repair is reported through the hook so
  callers can wire Prometheus counters / warnings
  (e.g. ``palatium_llm_json_parse_failures_total{repair=...}``).

Callers (supervisor, critic) catch :class:`LLMJSONError` and retry with
feedback instead of crashing the thread.
"""

from __future__ import annotations

import json
import re

from collections.abc import Callable
from typing import Any

#: A repair strategy takes the raw candidate string, returns repaired text.
RepairStrategy = Callable[[str], str]

#: Hook signature: ``(repair_name, candidate_head)`` after a non-trivial fix.
OnRepairHook = Callable[[str, str], None]

JSONValue = dict[str, Any] | list[Any]


# ────────────────────────── exceptions ──────────────────────────


class LLMJSONError(ValueError):
    """Raised when an LLM response contains no recoverable JSON."""


# ────────────────────────── extraction ──────────────────────────

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
# Trailing commas before } or ] — common LLM JSON defect.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _strip_fence(text: str) -> str:
    fence = _FENCE.search(text.strip())
    return fence.group(1).strip() if fence is not None else text.strip()


def _find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Index of the closing bracket for the structure starting at ``start``, or -1.

    String-aware: brackets inside JSON strings and escaped chars are ignored.
    """
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return index
    return -1


# ────────────────────────── repairs (pure functions) ──────────────────────────


def _noop(candidate: str) -> str:
    """Level 1 — trust the model."""
    return candidate


def _strip_inert_noise(candidate: str) -> str:
    """Trailing commas + invisible characters (BOM, zero-width space)."""
    repaired = _TRAILING_COMMA.sub(r"\1", candidate)
    return repaired.replace("\ufeff", "").replace("\u200b", "")


_RAW_CTRL_IN_STRING: dict[str, str] = {
    "\n": "\\n",
    "\r": "",
    "\t": "\\t",
}


def _escape_raw_control_chars(candidate: str) -> str:
    r"""Escape raw newlines/tabs ONLY inside JSON string values.

    Raw line breaks inside strings are illegal in strict JSON; models emit
    them frequently for long texts (official letters with addresses etc.).
    """
    out: list[str] = []
    in_string = False
    escape = False
    for ch in candidate:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            elif ch in _RAW_CTRL_IN_STRING:
                out.append(_RAW_CTRL_IN_STRING[ch])
                continue
        elif ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _heuristic_full_repair(candidate: str) -> str:
    """Last line of defence: heuristics from ``json_repair``.

    Handles unescaped inner quotes ("МБОО "Доброе дело" ...") that cannot be
    fixed deterministically. Local import keeps the deterministic path working
    without the optional dependency installed.
    """
    import json_repair  # pip install json-repair

    repaired = json_repair.repair_json(candidate, return_objects=False)
    return str(repaired)


DEFAULT_REPAIR_LADDER: tuple[tuple[str, RepairStrategy], ...] = (
    ("plain", _noop),
    ("inert_noise", _strip_inert_noise),
    ("raw_control_chars", _escape_raw_control_chars),
    ("heuristic_json_repair", _heuristic_full_repair),
)

_CANDIDATE_HEAD_LEN = 200


# ────────────────────────── codec ──────────────────────────


class JSONCodec:
    r"""Parser for LLM output that should contain a JSON payload.

    Parameters
    ----------
    on_repair:
        Optional telemetry callback invoked as ``hook(repair_name,
        candidate_head)`` whenever a non-``plain`` strategy succeeded.
        Recommended wiring::

            def metric_hook(name: str, head: str) -> None:
                JSON_PARSE_TOTAL.labels(repair=name).inc()
                logger.warning("LLM JSON repaired (%s): %.200s", name, head)

    ladder:
        Ordered strategies; first successful parse wins. Override in tests.

    Example
    -------
    >>> codec = JSONCodec(on_repair=metric_hook)
    >>> codec.loads('```json\n{"a": 1}\n```')
    {'a': 1}

    """

    def __init__(
        self,
        on_repair: OnRepairHook | None = None,
        ladder: tuple[tuple[str, RepairStrategy], ...] = DEFAULT_REPAIR_LADDER,
    ) -> None:
        self._on_repair = on_repair
        self._ladder = ladder

    # -- public API ---------------------------------------------------

    def loads(self, raw: str) -> Any:
        """Parse any top-level JSON value from LLM text.

        Raises
        ------
        LLMJSONError
            If no valid JSON could be extracted or recovered.

        """
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        candidate = self.extract(raw)
        errors: list[str] = []

        for name, strategy in self._ladder:
            try:
                result = json.loads(strategy(candidate))
            except json.JSONDecodeError as exc:
                errors.append(f"{name}: {exc.msg} at pos {exc.pos}")
                continue

            if name != "plain":
                self._report_repair(name, candidate)
            return result

        raise LLMJSONError(
            f"Unrecoverable JSON in LLM response (attempts: {'; '.join(errors)}): {candidate[:_CANDIDATE_HEAD_LEN]!r}"
        )

    def loads_object(self, raw: str) -> dict[str, Any]:
        """Like :meth:`loads`, but guarantees a top-level JSON object."""
        result = self.loads(raw)
        if not isinstance(result, dict):
            raise LLMJSONError(f"Expected JSON object, got {type(result).__name__}: {raw[:_CANDIDATE_HEAD_LEN]!r}")
        return result

    def loads_array(self, raw: str) -> list[Any]:
        """Like :meth:`loads`, but guarantees a top-level JSON array."""
        result = self.loads(raw)
        if not isinstance(result, list):
            raise LLMJSONError(f"Expected JSON array, got {type(result).__name__}: {raw[:_CANDIDATE_HEAD_LEN]!r}")
        return result

    # -- internals ----------------------------------------------------

    @staticmethod
    def extract(raw: str) -> str:
        """Return the first balanced ``{...}`` or ``[...]`` substring.

        Ignores prose around the payload and markdown fences. Prefers the
        structural token appearing earlier in the text; brackets inside
        strings are skipped by the scanner.
        """
        text = _strip_fence(raw)

        obj_start = text.find("{")
        arr_start = text.find("[")
        if obj_start < 0 and arr_start < 0:
            raise LLMJSONError(f"No JSON found in LLM response: {text[:_CANDIDATE_HEAD_LEN]!r}")

        if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start):
            end = _find_matching(text, arr_start, "[", "]")
            start = arr_start
        else:
            end = _find_matching(text, obj_start, "{", "}")
            start = obj_start

        if end < 0:
            raise LLMJSONError(f"Unbalanced JSON in LLM response: {text[:_CANDIDATE_HEAD_LEN]!r}")
        return text[start : end + 1]

    def _report_repair(self, name: str, candidate: str) -> None:
        head = candidate[:_CANDIDATE_HEAD_LEN]
        if self._on_repair is not None:
            self._on_repair(name, head)


# ───────────────────── default instance convenience ─────────────────────

_default_codec = JSONCodec()


def loads_llm_json(raw: str) -> Any:
    """Module-level shortcut over a default ``JSONCodec`` (no telemetry).

    Prefer an injected ``JSONCodec`` instance in application code; this
    function exists for one-liners, tests and notebooks.
    """
    return _default_codec.loads(raw)


def loads_llm_object(raw: str) -> dict[str, Any]:
    """Shortcut guaranteeing a top-level object."""
    return _default_codec.loads_object(raw)
