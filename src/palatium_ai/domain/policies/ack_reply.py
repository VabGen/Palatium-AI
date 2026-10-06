# src/palatium_ai/domain/policies/ack_reply.py

"""Deterministic ack/social reply — zero LLM (eval / cassette only).

Live planner routes social to ``format_only`` (Formatter LLM). This template is
kept for unit/eval assets that still assert locale-keyed acknowledgments —
not the production social path (055: classifier→canned reply is brittle).
"""

from __future__ import annotations

from palatium_ai.domain.content.content_document import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

# Primary greeting + one short offer-to-help line. Keys are BCP-47 language tags.
_ACK_BY_LANG: dict[str, tuple[str, str]] = {
    "ru": ("Здравствуйте!", "Чем могу помочь?"),
    "en": ("Hello!", "How can I help?"),
    "uk": ("Вітаю!", "Чим можу допомогти?"),
    "be": ("Вітаю!", "Чым магу дапамагчы?"),
    "de": ("Hallo!", "Womit kann ich helfen?"),
    "fr": ("Bonjour !", "Comment puis-je vous aider ?"),
    "es": ("¡Hola!", "¿En qué puedo ayudar?"),
    "zh": ("您好！", "有什么可以帮您？"),  # noqa: RUF001 — fullwidth CJK punctuation is correct
    "ar": ("مرحباً!", "كيف يمكنني المساعدة؟"),
    "he": ("שלום!", "במה אוכל לעזור?"),
}
_DEFAULT_ACK = _ACK_BY_LANG["en"]


class AckReplyPolicy:
    """Pure domain policy: locale → ContentDocument for eval ack fixtures."""

    @classmethod
    def build_document(cls, *, response_locale: str, confidence: float = 1.0) -> ContentDocument:
        """Return a frozen social acknowledgment document (no LLM)."""
        locale = ReplyLocalePolicy.normalize(response_locale) or "und"
        title, body = cls._lines_for_locale(locale)
        conf = min(max(confidence, 0.0), 1.0)
        # Keep "und" as-is — rewriting to en-US poisons sticky session locale
        # after short Cyrillic greetings that previously resolved as weak.
        return ContentDocument(
            schema_version=1,
            locale=locale,
            title=title,
            blocks=(ParagraphBlock(type="paragraph", text=body),),
            actions=(),
            meta=DocumentMeta(
                confidence=conf,
                requires_review=False,
                source_refs=(),
                interaction="none",
            ),
        )

    @classmethod
    def _lines_for_locale(cls, locale: str) -> tuple[str, str]:
        lang = locale.split("-", 1)[0].lower() if locale else "en"
        return _ACK_BY_LANG.get(lang, _DEFAULT_ACK)
