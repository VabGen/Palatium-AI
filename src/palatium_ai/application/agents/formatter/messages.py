# src/palatium_ai/application/agents/formatter/messages.py

"""User-facing lines for machine reason codes. Not a message catalog."""

from __future__ import annotations

from palatium_ai.domain.policies.locale import ReplyLocalePolicy

# EXCEPTION: 055 — two-locale map for machine reason codes, confirmed 2026-10-09.
_MESSAGES: dict[tuple[str, str], str] = {
    ("ru", "mcp_empty_result"): "По запросу ничего не найдено.",
    ("en", "mcp_empty_result"): "No results found for the request.",
    ("ru", "mcp_tool_error"): "Не удалось получить данные. Попробуйте позже.",
    ("en", "mcp_tool_error"): "Could not retrieve data. Try again later.",
}


def localized_message(locale: str, reason: str, *, user_text: str = "") -> str:
    """Map a machine reason to ru/en. Language comes from ReplyLocalePolicy."""
    lang = _language(locale, user_text)
    direct = _MESSAGES.get((lang, reason))
    if direct is not None:
        return direct
    family = ReplyLocalePolicy.locale_script_family(lang or locale or "und")
    fallback = "ru" if family == "cyrillic" else "en" if family == "latin" else ""
    if not fallback:
        return ""
    return _MESSAGES.get((fallback, reason), "")


def _language(locale: str, user_text: str) -> str:
    chosen = ReplyLocalePolicy.normalize(locale)
    if chosen is None or chosen == "und":
        chosen = ReplyLocalePolicy.normalize(ReplyLocalePolicy.resolve(user_text=user_text))
    if chosen is None or chosen == "und":
        family = ReplyLocalePolicy.script_family(ReplyLocalePolicy.strip_non_prose(user_text))
        if family == "cyrillic":
            return "ru"
        if family == "latin":
            return "en"
        return ""
    return chosen.split("-", 1)[0]
