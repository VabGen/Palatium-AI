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

The same guard owns two more leaks of the identical class — *our* notation
printed as content:

* page addresses (``[[page N]]``) that the parser writes into extracted text for
  citations, and that a verbatim "full text" answer copies out;
* formatting keywords (``bold``, ``italic``, ``none``) that the prompt playbook
  hands the model and that a weak model prints instead of applying
  (``**bold** — факт``).
"""

from __future__ import annotations

import re

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from palatium_ai.domain.content import ContentBlock
from palatium_ai.domain.content.page_markers import (
    PAGE_MARKER_RE,
    page_marker_hold_start,
    strip_page_markers,
)
from palatium_ai.domain.policies.assistant_identity import ASSISTANT_NAME, agent_role_labels
from palatium_ai.domain.policies.types import FORMATTER_STYLE_HINTS

if TYPE_CHECKING:
    from palatium_ai.domain.content import ContentDocument

#: Presentation style identifiers are prompt-playbook vocabulary, never answer text.
#: Closed set imported from the domain enum (one source, no drift — 010/050).
_STYLE_TERM_REPLACEMENTS: Mapping[str, str] = dict.fromkeys(FORMATTER_STYLE_HINTS, "выбранный формат")

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
    "verbosity_budget": "объём ответа",
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
    **_STYLE_TERM_REPLACEMENTS,
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

#: Names of the formatting primitives the prompt playbook hands the model. A model
#: that prints one instead of applying it ("**bold** — Выявлены…") shows the user
#: the instruction, not the answer — the same leak class as an internal field name
#: (055). Closed vocabulary of *our* markup, never a list of user phrases.
FORMATTING_KEYWORDS: frozenset[str] = frozenset(
    {"bold", "italic", "underline", "strikethrough", "strong", "emphasis", "monospace", "bolditalic"}
)
#: ``none`` is a style *value* ("no emphasis"). Ambiguous in prose ("none of the
#: files"), so it may only be dropped where it is structurally an emphasis label.
_EMPHASIS_STYLE_VALUES: frozenset[str] = FORMATTING_KEYWORDS | {"none"}
_STYLE_KEYWORD_ALTERNATION = "|".join(sorted((re.escape(word) for word in _EMPHASIS_STYLE_VALUES), key=len, reverse=True))
#: A style keyword in **label position** — separator inside (`**bold:**`) or after
#: (`**bold** —`) the bold run. A style name inside a sentence is left alone: only
#: the placeholder shape is a defect, so the marker is structural, not phrased.
_STYLE_SPAN_RE = re.compile(
    rf"\*\*[ \t]*(?:{_STYLE_KEYWORD_ALTERNATION})[ \t]*:[ \t]*\*\*[ \t]*"
    rf"|\*\*[ \t]*(?:{_STYLE_KEYWORD_ALTERNATION})[ \t]*\*\*[ \t]*[:—–-][ \t]*",
    re.IGNORECASE,
)
#: A bullet whose whole content was the placeholder disappears with it.
_EMPTY_BULLET_RE = re.compile(r"^[ \t]*[-*•][ \t]*$")
#: The only field that carries an emphasis *label*; a formatting keyword there is
#: never content (see ``_EMPHASIS_STYLE_VALUES``).
_EMPHASIS_FIELD = "emphasis"
#: In-place marker set by the walker and consumed by :func:`_prune`.
_DROP_KEY = "__palatium_drop__"
_DROPPED = object()
#: Typed blocks whose entries the contract requires (min_length=1): a block that
#: lost all of them has no shape left and must not reach the validator.
_CONTAINER_FIELDS: tuple[str, ...] = ("blocks", "items", "rows", "series", "labels", "columns")
#: Trailing fragment of such a span; held so a split stream cannot paint half of it.
_STYLE_SPAN_TAIL_RE = re.compile(r"\*\*[ \t]*(?P<kw>[A-Za-z]*)[ \t]*:?[ \t]*(?P<closed>\*\*)?[ \t]*(?P<sep>[:—–-])?[ \t]*$")
_MAX_STYLE_TAIL = 40

#: Literal markers that only mean something once fully assembled. A token stream
#: that cuts one in half paints the prefix before the sanitiser can see the term.
_STREAM_ANCHORS: tuple[str, ...] = ("attachment:", *tuple(INTERNAL_TERM_REPLACEMENTS))
#: An unterminated ``attachment:<uuid>[:name]`` reference held until a delimiter.
_REF_DELIMITER_RE = re.compile(r"[\s,;)\]]")
#: Style identifier standing alone (no partial-token handling here — ``safe_cut`` owns that).
_STYLE_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{'|'.join(re.escape(term) for term in FORMATTER_STYLE_HINTS)})(?![A-Za-z0-9_])"
)
#: Self-identification with an internal role ("Меня зовут Formatter", "I am a
#: Researcher worker"). Narrow by design: a role label anywhere else may be genuine
#: document content ("the Analyst report"), and rewriting that would corrupt an answer
#: about the user's file (017). Only the first-person identity claim is ours to fix.
_ROLE_LABEL_ALTERNATION = "|".join(sorted((re.escape(label) for label in agent_role_labels()), key=len, reverse=True))
_SELF_ID_RU_RE = re.compile(rf"(?P<prefix>\b(?:[Мм]еня зовут|[Яя]\s*[—–-])\s*)(?P<role>{_ROLE_LABEL_ALTERNATION})\b")
_SELF_ID_EN_RE = re.compile(
    rf"(?P<prefix>\b(?:I am|I'm)\s+)(?:(?:a|an|the)\s+)?(?P<role>{_ROLE_LABEL_ALTERNATION})\b(?:\s+worker)?"
)
#: Opener of a first-person identity claim; held across a stream chunk boundary so the
#: role label cannot arrive in a chunk that no longer carries its prefix.
_SELF_ID_OPEN_RE = re.compile(r"(?:\b[Мм]еня зовут\s+|\bI am\s+|\bI'm\s+)$")
#: Sentence / clause boundaries used to drop a meta claim about our prompt playbook
#: without touching the rest of the answer (punctuation, not a phrase list — 055).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])\s+")
_TERMINAL_PUNCT = ".!?…"
#: Identifiers continue across these chars, so a partial match preceded by one
#: cannot be the start of a fresh term (mirrors the left boundary of ``_TERM_RE``).
_WORD_CHAR_RE = re.compile(r"[0-9A-Za-z_]")
_MAX_HELD_REF_CHARS = 256
#: One adapter for the whole process: the block union is frozen at import time.
#: ``ContentBlock`` is an ``Annotated`` discriminated union — a valid runtime type
#: form that pyright's ``TypeForm`` (PEP 747) check does not model: TOOL_LIMITATION (017).
_BLOCK_ADAPTER: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)  # pyright: ignore[reportArgumentType]


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

        cleaned = cls._drop_style_meta(text)
        cleaned = strip_page_markers(cleaned)
        cleaned = cls._drop_style_placeholders(cleaned)
        cleaned = _SELF_ID_RU_RE.sub(lambda m: f"{m.group('prefix')}{ASSISTANT_NAME}", cleaned)
        cleaned = _SELF_ID_EN_RE.sub(lambda m: f"{m.group('prefix')}{ASSISTANT_NAME}", cleaned)
        cleaned = _ATTACHMENT_REF_RE.sub(_attachment_ref_replacement, cleaned)
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
            _TERM_RE.search(text)
            or _ATTACHMENT_REF_RE.search(text)
            or _MCP_REF_RE.search(text)
            or _BARE_UUID_RE.search(text)
            or _SELF_ID_RU_RE.search(text)
            or _SELF_ID_EN_RE.search(text)
            or _STYLE_SPAN_RE.search(text)
            or ("[" in text and PAGE_MARKER_RE.search(text))
        )

    @classmethod
    def _drop_style_placeholders(cls, text: str) -> str:
        """Remove a formatting keyword printed instead of applied.

        ``- **bold** — Выявлены…`` is the model echoing our playbook, not an answer
        label; the sentence after the separator is the content and must survive.
        A bullet that held nothing else disappears with its placeholder.
        """
        if not _STYLE_SPAN_RE.search(text):
            return text
        kept: list[str] = []
        for line in text.split("\n"):
            cleaned = _STYLE_SPAN_RE.sub("", line)
            if cleaned == line:
                kept.append(line)
                continue
            cleaned = cleaned.strip()
            if cleaned and not _EMPTY_BULLET_RE.match(cleaned):
                kept.append(cleaned)
        return "\n".join(kept)

    @classmethod
    def _drop_style_meta(cls, text: str) -> str:
        """Drop clauses that talk about our composition style, keep the answer.

        The model mirrors ``style_hint`` back as a claim ("…, как того требует стиль
        ``restructure_sections_icons``"). Rewriting the identifier alone leaves the
        meta claim in the answer, so the offending comma-clause is removed; a sentence
        made only of such clauses disappears entirely. When nothing is left (a bare
        identifier), the caller's term mapping produces a neutral phrase instead.
        """
        if not _STYLE_TOKEN_RE.search(text):
            return text
        kept_sentences: list[str] = []
        for sentence in _SENTENCE_SPLIT_RE.split(text):
            if not sentence:
                continue
            terminal = sentence[-1] if sentence[-1] in _TERMINAL_PUNCT else ""
            kept = [clause for clause in _CLAUSE_SPLIT_RE.split(sentence) if not _STYLE_TOKEN_RE.search(clause)]
            if not kept:
                continue
            rendered = " ".join(kept).rstrip(" ,;:—-")
            if terminal and not rendered.endswith(tuple(_TERMINAL_PUNCT)):
                rendered += terminal
            kept_sentences.append(rendered)
        return " ".join(kept_sentences).strip() or text

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
        return min(
            len(text),
            cls._anchor_cut(text),
            cls._ref_cut(text),
            cls._self_id_cut(text),
            cls._placeholder_cut(text),
            page_marker_hold_start(text),
        )

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
    def _self_id_cut(cls, text: str) -> int:
        """Hold a trailing self-identification opener until its role label arrives.

        The role guard is a two-part pattern ("Меня зовут" + role). A chunk boundary
        between the parts would let the whole sanitizer see a bare role label with no
        prefix, so the opener stays in the tail until the next chunk joins it.
        """
        match = _SELF_ID_OPEN_RE.search(text)
        return match.start() if match else len(text)

    @classmethod
    def _placeholder_cut(cls, text: str) -> int:
        """Hold a trailing ``**bold`` / ``**bold**`` until its separator is known.

        The placeholder rule needs the separator to know the span was a label; a
        chunk boundary that splits ``**bold**`` from `` — text`` would paint the
        keyword that the next frame can no longer remove (020).
        """
        if "**" not in text[-_MAX_STYLE_TAIL:]:
            return len(text)
        window = text[-_MAX_STYLE_TAIL:]
        match = _STYLE_SPAN_TAIL_RE.search(window)
        if match is None:
            return len(text)
        word = (match.group("kw") or "").strip().lower()
        if not any(keyword.startswith(word) for keyword in _EMPHASIS_STYLE_VALUES):
            return len(text)
        if match.group("closed") and match.group("sep"):
            # Complete placeholder: the same frame can drop it, no need to wait.
            return len(text)
        return len(text) - (len(window) - match.start())

    @classmethod
    def sanitize_document(cls, document: ContentDocument) -> ContentDocument:
        """Sanitize every user-visible string of a document (code/formula exempt).

        Re-validates only when something changed, so a clean document costs one
        dump and no model construction.
        """
        payload = document.model_dump(mode="json")
        if not cls._sanitize_node(payload):
            return document
        pruned = _prune(payload)
        if not isinstance(pruned, dict):
            return document
        return type(document).model_validate(pruned)

    @classmethod
    def sanitize_block(cls, block: ContentBlock) -> ContentBlock | None:
        """Sanitize one streamed block; ``None`` when nothing but our notation was in it.

        Structured preview frames reach the user before the document exists, so the
        guard cannot wait for ``sanitize_document`` — but it must not grow a second
        copy of the rules either (050). A frame that consisted only of a page address
        or a printed style keyword has no content to paint, so the caller drops it
        instead of painting an empty shell.
        """
        payload = block.model_dump(mode="json")
        if not cls._sanitize_node(payload):
            return block
        pruned = _prune(payload)
        if not isinstance(pruned, dict):
            return None
        return _BLOCK_ADAPTER.validate_python(pruned)

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
        emptied = False
        for key, value in node.items():
            if isinstance(value, str):
                if key == _EMPHASIS_FIELD and value.strip().lower() in _EMPHASIS_STYLE_VALUES:
                    # The label itself is the leaked instruction ("bold"/"none");
                    # the item text is the content and stays (055).
                    node[key] = None
                    changed = True
                    continue
                clean = cls.sanitize_text(value)
                if clean != value:
                    node[key] = clean
                    changed = True
                    stripped = clean.strip()
                    if value.strip() and (not stripped or _EMPTY_BULLET_RE.match(stripped)):
                        # Nothing but our notation was in this field (not even a
                        # bullet's text); the entry is dropped in ``_prune`` —
                        # an empty block fails the contract and padded whitespace
                        # would fake content (050).
                        emptied = True
            elif isinstance(value, dict | list):
                changed = cls._sanitize_node(value) or changed
        if emptied:
            node[_DROP_KEY] = True
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


def _prune(node: object) -> object:
    """Rebuild a sanitized payload without entries that lost all their content.

    A block or item whose text was only a page address (or a printed style
    keyword) has nothing left to show; the contract forbids empty text, so the
    entry is removed instead of being padded with whitespace (050 — no fake data).
    A container left with no entries goes with them.
    """
    if isinstance(node, dict):
        if node.get(_DROP_KEY):
            return _DROPPED
        pruned: dict[str, Any] = {}
        for key, value in node.items():
            if key == _DROP_KEY:
                continue
            child = _prune(value)
            if child is not _DROPPED:
                pruned[key] = child
        if "type" in pruned and any(not pruned.get(field) for field in _CONTAINER_FIELDS if field in pruned):
            return _DROPPED
        return pruned
    if isinstance(node, list):
        return [child for child in map(_prune, node) if child is not _DROPPED]
    return node


__all__ = ["FORMATTING_KEYWORDS", "INTERNAL_TERM_REPLACEMENTS", "InternalVocabularyPolicy"]
