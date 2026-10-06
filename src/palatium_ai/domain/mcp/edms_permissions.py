# src/palatium_ai/domain/mcp/edms_permissions.py

"""Словарь authority СЭД «Канцлер NEXT»: разбор и классификация (070, 090).

Источник истины — Java-enum ``Permission`` в JavaEdms (read-only reference, 090).
Ручной список authority запрещён: он дрейфует молча. Артефакт
``edms_authorities.py`` генерируется ``scripts/gen_edms_authorities.py``, а парсер
живёт здесь, чтобы генератор и гейт дрейфа использовали ОДИН код, а не две
похожие регулярки, которые разойдутся на следующей правке.

Рантайм-зависимости от JavaEdms нет: генерация читает референс на dev-машине
(там он есть), в пакет попадает только сгенерированная копия словаря. Описания
authority намеренно не переносятся — они не нужны ни гейту, ни policy, а их
копия в Python стала бы вторым источником русских текстов СЭД.
"""

from __future__ import annotations

import hashlib
import re

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "EDMS_ACTION_PREFIXES",
    "EdmsAction",
    "EdmsAuthority",
    "authority_fingerprint",
    "classify_authority",
    "parse_permission_java",
]

EdmsAction = Literal["create", "read", "update", "delete", "other"]

# Ось действия читается из имени authority (конвенция СЭД): CRUD-префикс есть у
# 291 из 303 имён. Остальные 12 (`LOTUS_NEXT_CONVERTER`, `SELECT_ORGANIZATION`,
# `ADD_USER_BASIC_AUTH`, …) получают ``other`` — их семантику задаёт СЭД,
# догадываться нельзя (090).
EDMS_ACTION_PREFIXES: dict[str, EdmsAction] = {
    "CREATE": "create",
    "READ": "read",
    "UPDATE": "update",
    "DELETE": "delete",
}

_AUTHORITY_MAX_CHARS = 128
_JAVA_ENUM_MARKER = "enum Permission"
_JAVA_ENTRY_RE = re.compile(
    r"^[ \t]*(?P<name>[A-Z][A-Z0-9_]*)\("
    r'\s*"(?P<authority>(?:[^"\\]|\\.)*)"\s*,\s*'
    r'"(?P<description>(?:[^"\\]|\\.)*)"\s*\)\s*[,;]?\s*$',
    re.MULTILINE,
)
# Safety net: любая indented UPPER_CASE-конструкция обязана быть разобрана. Без
# этого одна пропущенная строка (например, последняя константа enum с `;`)
# уносит authority из словаря молча — то, ради чего гейт и существует.
_JAVA_DECLARATION_RE = re.compile(r"^[ \t]+(?P<name>[A-Z][A-Z0-9_]*)\s*\(", re.MULTILINE)


class EdmsAuthority(BaseModel):
    """Один authority СЭД с разобранной осью действия.

    ``resource`` — литературный остаток имени после префикса действия, без
    нормализации: склеивать `READ_ALL_SUMMARY_*` с `READ_SUMMARY_*` — значит
    решать за СЭД (090). Согласованность ``action`` с ``side_effect`` пина
    инструмента проверяет будущая привязка authority → tool (W10b).
    """

    model_config = {"frozen": True}

    authority: str = Field(
        min_length=1,
        max_length=_AUTHORITY_MAX_CHARS,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="Authority string as declared by the EDMS Permission enum.",
    )
    action: EdmsAction = Field(description="CRUD axis derived from the authority name prefix.")
    resource: str = Field(
        min_length=1,
        max_length=_AUTHORITY_MAX_CHARS,
        description="Name remainder after the action prefix (literal, no normalization).",
    )


def classify_authority(authority: str) -> EdmsAuthority:
    """Разбирает authority на ось действия и ресурс по конвенции имени."""
    head, _, remainder = authority.partition("_")
    action = EDMS_ACTION_PREFIXES.get(head)
    if action is None:
        return EdmsAuthority(authority=authority, action="other", resource=authority)
    if not remainder:
        raise ValueError(f"authority {authority!r} has an action prefix but no resource")
    return EdmsAuthority(authority=authority, action=action, resource=remainder)


def parse_permission_java(source: str) -> tuple[EdmsAuthority, ...]:
    """Разбирает текст ``Permission.java`` в словарь authority.

    Падает громко, если файл перестал быть ожидаемым enum: молча вернуть пустой
    или частичный список — худший исход для гейта дрейфа.
    """
    if _JAVA_ENUM_MARKER not in source:
        raise ValueError(f"not a Permission enum source: marker {_JAVA_ENUM_MARKER!r} missing")

    # Объявления читаются отдельно от разбора: safety net должен срабатывать даже
    # когда не разобралась ни одна строка (иначе сообщение «пустой словарь» скрывает
    # настоящую причину — изменившийся layout enum).
    declared = {match.group("name") for match in _JAVA_DECLARATION_RE.finditer(source)}
    if not declared:
        raise ValueError("no Permission constants parsed — enum layout changed")

    seen: set[str] = set()
    parsed: list[EdmsAuthority] = []
    for name, authority, _description in _JAVA_ENTRY_RE.findall(source):
        if name != authority:
            raise ValueError(f"constant/authority mismatch: {name!r} declares {authority!r}")
        if authority in seen:
            raise ValueError(f"duplicate authority: {authority!r}")
        seen.add(authority)
        parsed.append(classify_authority(authority))

    missing = sorted(declared - seen)
    if missing:
        raise ValueError(f"declared but unparsed Permission constants: {missing}")
    return tuple(parsed)


def authority_fingerprint(authorities: Iterable[EdmsAuthority]) -> str:
    """SHA-256 по отсортированному набору authority — стабилен к порядку в файле."""
    canonical = "\n".join(sorted(item.authority for item in authorities))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
