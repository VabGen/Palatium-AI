# scripts/gen_edms_authorities.py

"""Генератор словаря authority СЭД из enum ``Permission`` (070, 090).

JavaEdms — read-only reference: референс читается здесь на dev-машине (в CI его
нет, путь в ``.gitignore``), а в пакет попадает только сгенерированная копия.
Ручной список authority запрещён — он дрейфует молча.

Использование::

    poetry run python scripts/gen_edms_authorities.py            # перегенерация
    poetry run python scripts/gen_edms_authorities.py --check     # гейт дрейфа

``--check`` требует референс и возвращает 3, если его нет: «не могу проверить» —
не то же самое, что «проверка прошла». Гейт в CI, который работает без
референса, — ``tests/unit/test_edms_authorities.py`` (внутренняя согласованность
артефакта).
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
PERMISSION_JAVA = _REPO_ROOT / "mcp_servers" / "edms" / "JavaEdms" / "edms" / "security" / "model" / "Permission.java"
OUTPUT_MODULE = _REPO_ROOT / "src" / "palatium_ai" / "domain" / "mcp" / "edms_authorities.py"

if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from palatium_ai.domain.mcp.edms_permissions import (  # noqa: E402  # sys.path bootstrap must run first
    EdmsAuthority,
    authority_fingerprint,
    parse_permission_java,
)

_EXIT_OK = 0
_EXIT_DRIFT = 1
_EXIT_NO_REFERENCE = 3

# Шапка — списком строк, а не одним блоком: внутри есть `"""`, и любой
# тройной литерал пришлось бы держать на других кавычках, а `ruff format`
# такие кавычки переписывает — артефакт перестал бы совпадать с рендером.
_DOCSTRING_TEMPLATE = (
    "Словарь authority СЭД «Канцлер NEXT» — СГЕНЕРИРОВАННЫЙ файл, не править вручную.",
    "",
    "Источник: enum ``Permission`` в JavaEdms (read-only reference, 090).",
    "Перегенерация: ``poetry run python scripts/gen_edms_authorities.py``.",
    "Проверка дрейфа: ``poetry run python scripts/gen_edms_authorities.py --check``",
    "и ``tests/unit/test_edms_authorities.py`` (внутренняя согласованность).",
    "",
    "В артефакте только имена: ось действия и ресурс выводит ``classify_authority``.",
    "Хранить ось рядом с именем — значит завести второй источник истины, который",
    "разойдётся с разбором имени (050).",
    "",
    "authorities: {count}",
    "fingerprint: {fingerprint}",
)

# Строки-выводы держим отдельно: в собранном виде одна из них длиннее 120 символов,
# а резать её внутри f-строки — значит получить E501 в самом генераторе.
# `map` вместо генератора — чтобы строка не упиралась в предел длины.
_DERIVED_AUTHORITIES_LINE = (
    "EDMS_AUTHORITIES: tuple[EdmsAuthority, ...] = tuple(map(classify_authority, _EDMS_AUTHORITY_TOKENS))"
)
_DERIVED_NAMES_LINE = "EDMS_AUTHORITY_NAMES: frozenset[str] = frozenset(_EDMS_AUTHORITY_TOKENS)"


def render(authorities: tuple[EdmsAuthority, ...]) -> str:
    """Собирает текст модуля детерминированно (порядок — по authority).

    Одна строка на authority и обязательная концевая запятая: без неё
    ``ruff format`` схлопнул бы кортеж в одну строку, и гейт «артефакт совпадает
    с рендером» начал бы падать на ровном месте.
    """
    ordered = sorted(authorities, key=lambda item: item.authority)
    fingerprint = authority_fingerprint(ordered)
    docstring = [line.format(count=len(ordered), fingerprint=fingerprint) for line in _DOCSTRING_TEMPLATE]

    lines = [
        "# src/palatium_ai/domain/mcp/edms_authorities.py",
        "",
        '"""',
        *docstring,
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from palatium_ai.domain.mcp.edms_permissions import EdmsAuthority, classify_authority",
        "",
        "__all__ = [",
        '    "EDMS_AUTHORITIES",',
        '    "EDMS_AUTHORITY_COUNT",',
        '    "EDMS_AUTHORITY_FINGERPRINT",',
        '    "EDMS_AUTHORITY_NAMES",',
        "]",
        "",
        f"EDMS_AUTHORITY_COUNT = {len(ordered)}",
        f'EDMS_AUTHORITY_FINGERPRINT = "{fingerprint}"',
        "",
        "# Только имена: ось действия и ресурс выводит classify_authority (см. шапку модуля).",
        "_EDMS_AUTHORITY_TOKENS: tuple[str, ...] = (",
    ]
    lines.extend(f'    "{item.authority}",' for item in ordered)
    lines.extend(
        [
            ")",
            "",
            _DERIVED_AUTHORITIES_LINE,
            "",
            _DERIVED_NAMES_LINE,
            "",
        ]
    )
    return "\n".join(lines)


def _load_reference() -> tuple[EdmsAuthority, ...]:
    if not PERMISSION_JAVA.is_file():
        raise FileNotFoundError(f"reference not available: {PERMISSION_JAVA}")
    return parse_permission_java(PERMISSION_JAVA.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Пишет артефакт или проверяет его синхронность с референсом."""
    parser = argparse.ArgumentParser(description="Generate the EDMS authority vocabulary from Permission.java.")
    parser.add_argument("--check", action="store_true", help="verify the committed module matches the reference")
    args = parser.parse_args(argv)

    try:
        authorities = _load_reference()
    except FileNotFoundError as exc:
        print(f"SKIP: {exc}", file=sys.stderr)
        print("JavaEdms is a local read-only checkout (.gitignore); --check needs it.", file=sys.stderr)
        return _EXIT_NO_REFERENCE

    rendered = render(authorities)
    current = OUTPUT_MODULE.read_text(encoding="utf-8") if OUTPUT_MODULE.is_file() else ""
    fingerprint = authority_fingerprint(authorities)[:12]

    if args.check:
        if current == rendered:
            print(f"OK: {len(authorities)} authorities in sync ({fingerprint}).")
            return _EXIT_OK
        print(f"DRIFT: {OUTPUT_MODULE} is stale — regenerate with scripts/gen_edms_authorities.py", file=sys.stderr)
        return _EXIT_DRIFT

    if current == rendered:
        print(f"unchanged: {len(authorities)} authorities ({fingerprint}).")
        return _EXIT_OK
    OUTPUT_MODULE.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"written: {OUTPUT_MODULE} ({len(authorities)} authorities, {fingerprint}).")
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
