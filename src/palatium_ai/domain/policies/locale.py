# src/palatium_ai/domain/policies/locale.py

"""Reply locale — user-facing language pin (055/065).

Locale is a presentation axis, not task_kind / continuation_kind.
Detection: Unicode script on prose (code/URLs stripped) + sticky prior.
No phrase lists. Cyrillic→ru-RU is a script default until an LLM hint
distinguishes ru/uk/be (same call as Intent, optional).
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.content.content_document import ContentBlock

ScriptFamily = Literal["cyrillic", "latin", "han", "arabic", "hebrew", "other", "weak"]

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# Machine envelopes are Latin-heavy protocol, not user prose (HITL resume, tool fences).
_PROTOCOL_FENCE = re.compile(
    r"<<<HITL_CHOICE_RESUME[^>]*>>>|"
    r"<<<UNTRUSTED_HITL_LABEL[\s\S]*?<<<END_UNTRUSTED_HITL_LABEL>>>|"
    r"<<<UNTRUSTED_TOOL_OUTPUT[^>]*>>>[\s\S]*?<<<END_UNTRUSTED_TOOL_OUTPUT>>>",
    re.IGNORECASE,
)
_HITL_RESUME_MARKER = "HITL_CHOICE_RESUME"
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")

_WEAK_LETTER_MIN = 8
_DOMINANT_RATIO = 0.55

# Short unanimous Latin ("ok", "hi") stays weak so sticky prior wins.
# Short Cyrillic/Han/Arabic/Hebrew is a real language signal («Привет»).
_STRONG_WHEN_SHORT: frozenset[ScriptFamily] = frozenset({"cyrillic", "han", "arabic", "hebrew"})

_SCRIPT_DEFAULT: dict[ScriptFamily, str] = {
    "cyrillic": "ru-RU",
    "latin": "en-US",
    "han": "zh-CN",
    "arabic": "ar",
    "hebrew": "he",
}

_CYRILLIC_LANGS = frozenset({"ru", "uk", "be", "bg", "sr", "mk"})
_HAN_LANGS = frozenset({"zh", "ja", "ko"})
_ARABIC_LANGS = frozenset({"ar", "fa", "ur"})


def _char_script(ch: str) -> ScriptFamily | None:
    """Map one alphabetic char to a script bucket; None if not a letter."""
    if not ch.isalpha():
        return None
    code = ord(ch)
    if 0x0400 <= code <= 0x04FF or 0x0500 <= code <= 0x052F:
        return "cyrillic"
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
        return "arabic"
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
        return "han"
    if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or 0x00C0 <= code <= 0x024F:
        return "latin"
    return "other"


def _steps_and_table_parts(block: object) -> list[str]:
    from palatium_ai.domain.content.content_document import StepsBlock, TableBlock

    if isinstance(block, StepsBlock):
        parts: list[str] = []
        for item in block.items:
            parts.append(item.title)
            if item.body:
                parts.append(item.body)
        return parts
    if isinstance(block, TableBlock):
        parts = list(block.columns)
        for row in block.rows:
            parts.extend(row)
        return parts
    return []


def _block_prose_parts(block: ContentBlock) -> list[str]:
    """Extract user-facing strings from one block (skip code/formula)."""
    from palatium_ai.domain.content.content_document import (
        CalloutBlock,
        CodeBlock,
        DividerBlock,
        FormulaBlock,
        HeadingBlock,
        ListBlock,
        ParagraphBlock,
        WidgetBlock,
    )

    if isinstance(block, CodeBlock | FormulaBlock | DividerBlock):
        return []
    if isinstance(block, HeadingBlock | ParagraphBlock):
        return [block.text]
    if isinstance(block, CalloutBlock):
        return [*([block.title] if block.title else []), block.body]
    if isinstance(block, ListBlock):
        return [item.text for item in block.items]
    if isinstance(block, WidgetBlock):
        return [block.title] if block.title else []
    return _steps_and_table_parts(block)


class ReplyLocalePolicy:
    """Pure policy: resolve BCP-47 for user-facing replies."""

    @classmethod
    def normalize(cls, locale: str | None) -> str | None:
        """Return canonical BCP-47 or None if invalid/empty."""
        _ = cls
        if locale is None:
            return None
        raw = locale.strip()
        if not raw:
            return None
        # Accept "ru" / "en-us" → ru / en-US
        parts = raw.replace("_", "-").split("-", 1)
        lang = parts[0].lower()
        # ISO 639-1 (2) or undetermined und (639-3); other 3-letter tags rejected for now.
        if not lang.isalpha() or len(lang) not in {2, 3}:
            return None
        if len(lang) == 3 and lang != "und":
            return None
        if len(parts) == 1:
            candidate = lang
        else:
            region = parts[1].upper()
            if len(region) != 2 or not region.isalpha():
                return None
            if lang == "und":
                return None
            candidate = f"{lang}-{region}"
        if not _LOCALE_RE.match(candidate):
            return None
        return candidate

    @classmethod
    def strip_non_prose(cls, text: str) -> str:
        """Drop code fences, protocol envelopes, and URLs before script detection."""
        _ = cls
        cleaned = _CODE_FENCE.sub(" ", text)
        cleaned = _PROTOCOL_FENCE.sub(" ", cleaned)
        return _URL.sub(" ", cleaned)

    @classmethod
    def script_family(cls, text: str) -> ScriptFamily:
        """Dominant letter script, or weak/other when signal is insufficient."""
        _ = cls
        counts: dict[ScriptFamily, int] = {
            "cyrillic": 0,
            "latin": 0,
            "han": 0,
            "arabic": 0,
            "hebrew": 0,
            "other": 0,
        }
        for ch in text:
            family = _char_script(ch)
            if family is not None:
                counts[family] += 1

        total = sum(counts.values())
        if total == 0:
            return "weak"
        family, n = max(counts.items(), key=lambda item: item[1])
        if total < _WEAK_LETTER_MIN:
            # Unanimous distinctive script: pin even on short greetings (055).
            if family in _STRONG_WHEN_SHORT and n == total:
                return family
            return "weak"
        if n / total < _DOMINANT_RATIO:
            return "weak"
        if family == "other":
            return "other"
        return family

    @classmethod
    def locale_script_family(cls, locale: str) -> ScriptFamily:
        """Map BCP-47 language subtag to script family."""
        normalized = cls.normalize(locale)
        if normalized is None:
            return "other"
        lang = normalized.split("-", 1)[0]
        if lang in _CYRILLIC_LANGS:
            return "cyrillic"
        if lang in _HAN_LANGS:
            return "han"
        if lang in _ARABIC_LANGS:
            return "arabic"
        if lang == "he":
            return "hebrew"
        if lang == "und":
            return "weak"
        return "latin"

    @classmethod
    def resolve(
        cls,
        *,
        user_text: str,
        prior_locale: str | None = None,
        ui_locale: str | None = None,
        hint_locale: str | None = None,
    ) -> str:
        """Resolve sticky response locale for this turn.

        Priority: strong user prose / hint → sticky prior (same script) →
        script default → ui → und.

        HITL choice resume envelopes are protocol carriers (often English
        markers + option labels) — never flip sticky locale from them.
        """
        prior = cls.normalize(prior_locale)
        ui = cls.normalize(ui_locale)
        hint = cls.normalize(hint_locale)
        if _HITL_RESUME_MARKER in user_text:
            return prior or ui or "und"

        prose = cls.strip_non_prose(user_text)
        family = cls.script_family(prose)

        if family == "weak":
            if hint is not None:
                return hint
            return prior or ui or "und"

        if hint is not None and cls.locale_script_family(hint) == family:
            return hint

        # Stickiness: keep prior when it already matches this script (ru↔uk bounce).
        if prior is not None and cls.locale_script_family(prior) == family:
            return prior

        default = _SCRIPT_DEFAULT.get(family)
        if default is not None:
            return default
        return prior or ui or "und"

    @classmethod
    def prose_matches_locale(cls, prose: str, locale: str) -> bool:
        """True when prose script is compatible with locale (or too weak to judge)."""
        normalized = cls.normalize(locale)
        if normalized is None or normalized == "und":
            return True
        family = cls.script_family(cls.strip_non_prose(prose))
        if family in {"weak", "other"}:
            return True
        return family == cls.locale_script_family(normalized)

    @classmethod
    def document_prose(cls, document: ContentDocument) -> str:
        """User-facing strings excluding code/formula (language of identifiers ignored)."""
        _ = cls
        parts: list[str] = []
        if document.title:
            parts.append(document.title)
        for block in document.blocks:
            parts.extend(_block_prose_parts(block))
        parts.extend(action.label for action in document.actions)
        return "\n".join(parts)
