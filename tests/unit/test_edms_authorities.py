"""Гейт словаря authority СЭД: синхронность с JavaEdms и защита артефакта (070, 090, 075).

Две разные проверки, не путать:

* **артефакт ↔ референс** — настоящий гейт дрейфа; работает только там, где есть
  локальный read-only checkout JavaEdms (он в ``.gitignore``), в CI скипается;
* **артефакт ↔ собственный рендер** — работает всегда и ловит ручную правку
  сгенерированного файла (иначе «не править руками» осталось бы вежливой просьбой).

Ручной список authority запрещён: дрейф ищется по референсу, а не по памяти.

Почему парсер живёт в ``domain/mcp``, а не в тесте: генератор и гейт обязаны
использовать ОДИН код. Две «почти одинаковые» регулярки разошлись бы на первой же
правке enum — и разошлись бы молча.
"""

from __future__ import annotations

import functools
import importlib.util
import pathlib
import sys

from collections import Counter

import pytest

from pydantic import ValidationError

from palatium_ai.domain.mcp.edms_authorities import (
    EDMS_AUTHORITIES,
    EDMS_AUTHORITY_COUNT,
    EDMS_AUTHORITY_FINGERPRINT,
    EDMS_AUTHORITY_NAMES,
)
from palatium_ai.domain.mcp.edms_permissions import (
    EDMS_ACTION_PREFIXES,
    EdmsAuthority,
    authority_fingerprint,
    classify_authority,
    parse_permission_java,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ARTIFACT_PATH = _REPO_ROOT / "src" / "palatium_ai" / "domain" / "mcp" / "edms_authorities.py"
_REFERENCE_PATH = _REPO_ROOT / "mcp_servers" / "edms" / "JavaEdms" / "edms" / "security" / "model" / "Permission.java"
_GENERATOR_PATH = _REPO_ROOT / "scripts" / "gen_edms_authorities.py"

_CRUD_ACTIONS = frozenset({"create", "read", "update", "delete"})

_JAVAEDMS_HEADER = 'public enum Permission {\n    CREATE_DOCUMENT("CREATE_DOCUMENT", "Создать документ");\n}'


@functools.lru_cache(maxsize=1)
def _load_generator():
    """Импортирует scripts/gen_edms_authorities.py один раз (кеш — как в test_make_helpers)."""
    spec = importlib.util.spec_from_file_location("gen_edms_authorities", _GENERATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_edms_authorities"] = module
    spec.loader.exec_module(module)
    return module


# ── Инварианты артефакта (работают без референса) ────────────────────────────────


def test_artifact_is_hand_edit_proof() -> None:
    """Сгенерированный файл обязан совпадать с рендером из своего же содержимого."""
    mod = _load_generator()
    assert _ARTIFACT_PATH.read_text(encoding="utf-8") == mod.render(EDMS_AUTHORITIES), (
        "edms_authorities.py отредактирован вручную или устарел — "
        "перегенерируй: poetry run python scripts/gen_edms_authorities.py"
    )


def test_artifact_has_no_reference_path() -> None:
    """В пакет попадает копия словаря, а не путь к checkout'у JavaEdms (090)."""
    assert "mcp_servers" not in _ARTIFACT_PATH.read_text(encoding="utf-8")


def test_count_matches_entries() -> None:
    assert len(EDMS_AUTHORITIES) == EDMS_AUTHORITY_COUNT


def test_fingerprint_matches_entries() -> None:
    assert authority_fingerprint(EDMS_AUTHORITIES) == EDMS_AUTHORITY_FINGERPRINT


def test_names_are_unique_and_sorted() -> None:
    names = [item.authority for item in EDMS_AUTHORITIES]
    assert len(set(names)) == len(names), "duplicate authority in artifact"
    assert names == sorted(names), "artifact must be deterministically ordered"


def test_name_index_matches_entries() -> None:
    assert frozenset(item.authority for item in EDMS_AUTHORITIES) == EDMS_AUTHORITY_NAMES


def test_every_entry_matches_its_classification() -> None:
    """Ось действия и ресурс в артефакте — не свободный текст, а разбор имени."""
    for item in EDMS_AUTHORITIES:
        assert item == classify_authority(item.authority), f"classification drift for {item.authority}"


def test_crud_axes_are_populated_and_other_is_explicit() -> None:
    """CRUD-префиксы реально покрывают словарь; `other` не маскирует опечатку."""
    by_action = Counter(item.action for item in EDMS_AUTHORITIES)
    for action in _CRUD_ACTIONS:
        assert by_action[action] > 0, f"no authority with action={action}"
    for item in EDMS_AUTHORITIES:
        if item.action == "other":
            assert item.resource == item.authority, "non-CRUD authority must keep its full name as resource"
        else:
            assert item.resource != item.authority, "CRUD authority must carry a stripped resource"


# ── Разбор enum: контракт парсера (на фикстурах, без референса) ──────────────────


def test_parser_accepts_semicolon_terminated_last_constant() -> None:
    """Последняя константа enum завершается `;` — самая частая молчаливая потеря."""
    parsed = parse_permission_java(_JAVAEDMS_HEADER)
    assert [item.authority for item in parsed] == ["CREATE_DOCUMENT"]


@pytest.mark.parametrize(
    "source, match",
    (
        ('public enum Other {\n    READ_X("READ_X", "x");\n}', "marker"),
        ("public enum Permission {\n}", "no Permission constants parsed"),
        ('public enum Permission {\n    READ_X("READ_Y", "x");\n}', "constant/authority mismatch"),
        (
            'public enum Permission {\n    READ_X("READ_X", "x"),\n    READ_X("READ_X", "x");\n}',
            "duplicate authority",
        ),
        ('public enum Permission {\n    READ_X(READ_X, "x");\n}', "unparsed Permission constants"),
        ('public enum Permission {\n    CREATE_DOCUMENT("CREATE_DOCUMENT");\n}', "unparsed Permission constants"),
    ),
)
def test_parser_fails_loudly_on_broken_source(source: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_permission_java(source)


def test_classification_rejects_prefix_without_resource() -> None:
    with pytest.raises(ValueError, match="no resource"):
        classify_authority("CREATE_")


def test_authority_model_is_frozen_and_shape_checked() -> None:
    item = EdmsAuthority(authority="READ_DOCUMENT", action="read", resource="DOCUMENT")
    with pytest.raises(ValidationError, match="frozen"):
        item.authority = "OTHER"  # type: ignore[misc]  # проверяем именно запрет мутации
    with pytest.raises(ValidationError, match="String should match pattern"):
        EdmsAuthority(authority="read_document", action="read", resource="DOCUMENT")


def test_action_prefixes_cover_every_crud_action() -> None:
    assert set(EDMS_ACTION_PREFIXES.values()) == _CRUD_ACTIONS


# ── Дрейф против референса JavaEdms (только там, где он есть) ────────────────────


def test_artifact_matches_javaedms_reference() -> None:
    if not _REFERENCE_PATH.is_file():
        pytest.skip(f"JavaEdms reference not checked out ({_REFERENCE_PATH})")
    from_reference = parse_permission_java(_REFERENCE_PATH.read_text(encoding="utf-8"))
    assert sorted(item.authority for item in from_reference) == [item.authority for item in EDMS_AUTHORITIES], (
        "Permission.java изменился: перегенерируй словарь (scripts/gen_edms_authorities.py)"
    )
    assert authority_fingerprint(from_reference) == EDMS_AUTHORITY_FINGERPRINT
