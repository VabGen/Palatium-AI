# src/palatium_ai/domain/policies/internal_vocabulary.py

"""Closed internal contract vocabulary must never reach the user (020, 055).

We hand the model our own field names twice: as JSON payload keys
(``attachment_context``, ``prior_context``, ``memory_hints``, …) and inside the
system prompts ("If ``attachment_context`` is non-empty …"). The model then
mirrors that vocabulary back into the answer and into HITL card labels, the turn
is persisted, and the next turn feeds the jargon in as ``prior_context`` — so the
leak cascades (055: the contract is buggy, not the phrase).

Two layers fix that:

1. the LLM-facing payload/prompt vocabulary is user-domain, not internal
   (researcher/formatter payload builders, option synthesizer, prompts);
2. this policy is the deterministic, LLM-independent guard on the way out — the
   same role ``domain.attachments.citations.sanitize_source_refs`` plays for
   citation chips. A prompt instruction alone is not a guardrail (020).

The mapping is a *presentation dictionary* (internal identifier → neutral user
word), deliberately not an intent phrase list (055): unknown jargon is never
guessed, and code/formula block content is left untouched because it is not
prose.
"""

from __future__ import annotations

import re

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from palatium_ai.domain.content import ContentBlock

if TYPE_CHECKING:
    from palatium_ai.domain.content import ContentDocument

#: Internal identifier → neutral user-facing wording. Ordered longest-first:
#: Python ``re`` alternation is first-match, so ``context_packet_json`` must be
#: tried before ``context_packet``. Both the internal spellings and the
#: user-domain payload keys are listed: the model quotes whichever spelling it
#: was handed, and neither may reach the user.
INTERNAL_TERM_REPLACEMENTS: Mapping[str, str] = {
    "context_packet_json": "контекст",
    "context_packet": "контекст",
    "attachment_context": "вложения",
    "attached_files": "вложения",
    "prior_context": "предыдущий ответ",
    "previous_answer": "предыдущий ответ",
    "memory_hints": "память о вас",
    "user_facts": "память о вас",
    "user_request": "запрос",
    "worker_summary": "черновик ответа",
    "critic_summary": "результат проверки",
    "underspecification_kind": "недостающая деталь",
    "requires_user_choice": "нужен выбор",
    "requires_review": "нужна проверка",
    "revision_feedback": "замечания к ответу",
    "dialog_history": "история диалога",
    "format_hints": "настройки формата",
    "candidate_capabilities": "возможности",
    "skill_references": "материалы навыков",
    "skill_catalog": "доступные навыки",
    "source_refs": "источники",
    "response_locale": "язык ответа",
    "style_hint": "стиль ответа",
    "task_kind": "тип запроса",
    "route_plan": "план",
    "user_text": "запрос пользователя",
    "final_text": "текст ответа",
}

#: Blocks whose payload is machine text, not prose — sanitizing them would
#: silently rewrite the user's code (055).
_VERBATIM_BLOCK_TYPES = frozenset({"code", "formula"})

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_TERM_ALTERNATION = "|".join(re.escape(term) for term in INTERNAL_TERM_REPLACEMENTS)
# Word-ish boundary: snake_case identifiers contain ``_``, so ``_`` counts as part
# of the token — ``memory_hints`` must not match inside ``my_memory_hints_x``.
_TERM_RE = re.compile(rf"(?<![A-Za-z0-9_])(?P<term>{_TERM_ALTERNATION})(?![A-Za-z0-9_])")
_BACKTICKED_TERM_RE = re.compile(rf"`\s*(?P<term>{_TERM_ALTERNATION})\s*`")
_BARE_TERM_RE = re.compile(rf"(?<![A-Za-z0-9_])(?P<term>{_TERM_ALTERNATION})(?![A-Za-z0-9_])")
# ``attachment:<uuid>`` / ``attachment:<uuid>:file.pdf`` — traffic-grade refs the
# model copies out of the fence. The visible filename survives, the id never does.
_ATTACHMENT_REF_RE = re.compile(rf"attachment:(?:(?P<id>{_UUID}):)?(?P<name>[^\s,;)\]]+)")
_ATTACHMENT_ID_ONLY_RE = re.compile(rf"attachment:(?P<id>{_UUID})")
_MCP_REF_RE = re.compile(r"mcp:[A-Za-z0-9_]+\.[A-Za-z0-9_]+")
_BARE_UUID_RE = re.compile(rf"(?<![0-9a-fA-F-]){_UUID}(?![0-9a-fA-F-])")
_WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?)\]])")

#: Literal markers that only mean something once fully assembled. A token stream
#: that cuts one in half paints the prefix before the sanitiser can see the term.
_STREAM_ANCHORS: tuple[str, ...] = ("attachment:", *tuple(INTERNAL_TERM_REPLACEMENTS))
#: An unterminated ``attachment:<uuid>[:name]`` reference held until a delimiter.
_REF_DELIMITER_RE = re.compile(r"[\s,;)\]]")
#: Identifiers continue across these chars, so a partial match preceded by one
#: cannot be the start of a fresh term (mirrors the left boundary of ``_TERM_RE``).
_WORD_CHAR_RE = re.compile(r"[0-9A-Za-z_]")
_MAX_HELD_REF_CHARS = 256
#: One adapter for the whole process: the block union is frozen at import time.
_BLOCK_ADAPTER: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)


class InternalVocabularyPolicy:
    """Deterministic rewrite of internal jargon in user-facing text."""

    @staticmethod
    def find_terms(text: str) -> tuple[str, ...]:
        """Internal identifiers present in ``text`` (observability + contract tests)."""
        return tuple(sorted({match.group("term").lower() for match in _TERM_RE.finditer(text)}))

    @staticmethod
    def has_terms(text: str) -> bool:
        return _TERM_RE.search(text) is not None

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Replace internal identifiers with user words; drop traffic-grade ids.

        Idempotent, allocation-free when nothing matches (the hot path streams
        every draft through here).
        """
        if not text:
            return text
        if not cls._needs_rewrite(text):
            return text

        cleaned = _ATTACHMENT_REF_RE.sub(_attachment_ref_replacement, text)
        cleaned = _ATTACHMENT_ID_ONLY_RE.sub("файл", cleaned)
        cleaned = _MCP_REF_RE.sub("инструмент", cleaned)
        cleaned = _BARE_UUID_RE.sub("файл", cleaned)
        cleaned = _BACKTICKED_TERM_RE.sub(lambda m: _replacement(m.group("term")), cleaned)
        cleaned = _BARE_TERM_RE.sub(lambda m: _replacement(m.group("term")), cleaned)
        cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned)
        return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)

    @classmethod
    def _needs_rewrite(cls, text: str) -> bool:
        return bool(
            _TERM_RE.search(text) or _ATTACHMENT_REF_RE.search(text) or _MCP_REF_RE.search(text) or _BARE_UUID_RE.search(text)
        )

    @classmethod
    def safe_cut(cls, text: str) -> int:
        """Index up to which ``text`` may be painted without splitting a term.

        A token stream must HOLD ``text[index:]`` for the next chunk: a marker cut
        in half (``…memory_hi`` + ``nts…``) paints its prefix before this policy can
        see the whole term, so per-chunk sanitising alone is not a guardrail (020).

        Returns ``len(text)`` when the whole buffer is safe to emit.
        """
        if not text:
            return 0
        return max(0, min(len(text), cls._anchor_cut(text), cls._ref_cut(text)))

    @classmethod
    def _anchor_cut(cls, text: str) -> int:
        """Cut before a partial trailing anchor that could still grow into a term.

        A partial match only counts when it starts at a token boundary: ``"world"``
        ends with ``"d"`` — the first letter of ``dialog_history`` — but the ``"l"``
        before it proves an ordinary word, so holding that back would stall every
        frame ending on a common letter for no reason.
        """
        cut = len(text)
        for anchor in _STREAM_ANCHORS:
            for size in range(min(len(anchor) - 1, len(text)), 0, -1):
                if not text.endswith(anchor[:size]):
                    continue
                start = len(text) - size
                if start == 0 or not _WORD_CHAR_RE.match(text[start - 1]):
                    cut = min(cut, start)
                break
        return cut

    @classmethod
    def _ref_cut(cls, text: str) -> int:
        """Hold an unterminated ``attachment:<uuid>[:name]`` reference in the tail."""
        start = text.rfind("attachment:")
        if start < 0 or len(text) - start > _MAX_HELD_REF_CHARS:
            return len(text)
        return len(text) if _REF_DELIMITER_RE.search(text, start) else start

    @classmethod
    def sanitize_document(cls, document: ContentDocument) -> ContentDocument:
        """Sanitize every user-visible string of a document (code/formula exempt).

        Re-validates only when something changed, so a clean document costs one
        dump and no model construction.
        """
        payload = document.model_dump(mode="json")
        if not cls._sanitize_node(payload):
            return document
        return type(document).model_validate(payload)

    @classmethod
    def sanitize_block(cls, block: ContentBlock) -> ContentBlock:
        """Sanitize one streamed block (same rules as the whole document).

        Structured preview frames reach the user before the document exists, so the
        guard cannot wait for ``sanitize_document`` — but it must not grow a second
        copy of the rules either (050).
        """
        payload = block.model_dump(mode="json")
        if not cls._sanitize_node(payload):
            return block
        return _BLOCK_ADAPTER.validate_python(payload)

    @classmethod
    def _sanitize_node(cls, node: object) -> bool:
        """Walk a dumped document in place; True when any string was rewritten."""
        if isinstance(node, dict):
            if node.get("type") in _VERBATIM_BLOCK_TYPES:
                return False
            return cls._sanitize_mapping(node)
        if isinstance(node, list):
            return cls._sanitize_sequence(node)
        return False

    @classmethod
    def _sanitize_mapping(cls, node: dict[str, Any]) -> bool:
        changed = False
        for key, value in node.items():
            if isinstance(value, str):
                clean = cls.sanitize_text(value)
                if clean != value:
                    node[key] = clean
                    changed = True
            elif isinstance(value, dict | list):
                changed = cls._sanitize_node(value) or changed
        return changed

    @classmethod
    def _sanitize_sequence(cls, node: list[Any]) -> bool:
        changed = False
        for index, value in enumerate(node):
            if isinstance(value, str):
                clean = cls.sanitize_text(value)
                if clean != value:
                    node[index] = clean
                    changed = True
            elif isinstance(value, dict | list):
                changed = cls._sanitize_node(value) or changed
        return changed


def _replacement(term: str) -> str:
    return INTERNAL_TERM_REPLACEMENTS.get(term.lower(), INTERNAL_TERM_REPLACEMENTS.get(term, term))


def _attachment_ref_replacement(match: re.Match[str]) -> str:
    """Keep the user-facing filename, drop the internal id."""
    name = (match.group("name") or "").strip()
    return name if name and not _BARE_UUID_RE.fullmatch(name) else "файл"


__all__ = ["INTERNAL_TERM_REPLACEMENTS", "InternalVocabularyPolicy"]
