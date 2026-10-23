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
    # Level 5 graceful degradation: the module is down, not the request. Say which
    # capability is missing and what still works — never a bare failure plaque.
    ("ru", "mcp_server_unavailable"): (
        "Модуль корпоративного поиска временно недоступен. Попробуйте позже "
        "или уточните запрос — часть вопросов можно решить без внешней базы."
    ),
    ("en", "mcp_server_unavailable"): (
        "The corporate search module is temporarily unavailable. Try again later, "
        "or refine the request — some questions can be answered without the external base."
    ),
    ("ru", "mcp_server_unavailable_with_files"): (
        "Модуль корпоративного поиска временно недоступен, поэтому в корпоративной базе "
        "я сейчас не ищу. Могу проанализировать файлы, приложенные к этому сообщению."
    ),
    ("en", "mcp_server_unavailable_with_files"): (
        "The corporate search module is temporarily unavailable, so I cannot search the "
        "corporate base right now. I can still analyse the files attached to this message."
    ),
    # Attached but unreadable (OCR/extraction produced nothing). The turn must say
    # exactly that — a canned greeting here reads as if the file had been analyzed.
    ("ru", "attachment_text_unavailable"): (
        "Не удалось извлечь текст из приложенного файла. "
        "Попробуйте загрузить другой формат или проверьте качество скана."
    ),
    ("en", "attachment_text_unavailable"): (
        "Could not extract text from the attached file. "
        "Try another format, or check the scan quality."
    ),
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
