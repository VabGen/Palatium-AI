# B.4 — Fix proposal: user-namespace recall bleed (P0-B)

**Дата:** 2026-10-13  
**Симптом:** A.2d FAIL — user-ns fact про чужой attachment попадает в T1 `memory_hits`.  
**Не трогать:** P0-A (`get_many` / rehydrate / dialog). Scratchpad pin score=10000 — вне scope (B.1).

---

## Варианты

| # | Идея | Greens A.2d? | Риск | Diff |
|---|---|---|---|---|
| 1 | Строгий thread-scope: user-ns факты только если entry.thread_id == current | да* | нужна provenance на Write; schema/метаданные | >30 лок / миграция |
| 2 | `source='episodic_user'` + weight cap=100 | **нет** | маркер всё ещё в hits; Contextualizer всё равно видит текст | малый |
| 3 | Skip user-ns если у thread уже есть hits | частично | хрупко: пустой thread → bleed; полный → режет prefs | малый |
| 4 | Запрет cross-thread recall по умолчанию (убрать user_ns из `_recall_namespaces`) | да | ломает prefs («меня зовут Геннадий», tables) — `test_recall_merges_user_namespace_preferences` | ~3 строки |

\*вариант 1 в буквальном виде требует thread_id на user-ns entries — сейчас их нет (`user_namespace` = `("user", user_id)`).

---

## Выбор: **1′ / 4′ — kind-gate на user_namespace**

`user_namespace` документирован как *«User preferences / durable profile facts»* (`namespaces.py:13-15`). Episode/file asks туда писать не должны попадать в hot-path Select.

**Правило:** при select durable hits, если `namespace[0] == "user"`, принимать только `kind == "preference"`.  
`fact` / `episode` / `incident` / прочее из user-ns **не** входят в `memory_hits` текущего треда.

Эквивалент строгого scope для эпизодов без Write-миграции; prefs остаются cross-thread (контракт 060 profile).

Почему не 2/3/4-raw:
- 2 не зеленится A.2d (assert — отсутствие текста, не score).
- 3 зависит от порядка/бюджета, не принцип.
- 4 без carve-out prefs — регресс identity/format prefs.

---

## Diff sketch (≤30 строк) — `memory_recall.py`

```python
# рядом с _QUERY_INDEPENDENT_KINDS
_USER_NS_HOT_PATH_KINDS = frozenset({"preference"})

# в _select_durable_hits, внутри цикла ranked:
for idx, (namespace, item) in enumerate(ranked):
    if _is_user_namespace(namespace):
        kind = str(item.get("kind", "fact")).strip().lower() or "fact"
        if kind not in _USER_NS_HOT_PATH_KINDS:
            continue
    hit = _durable_hit_from_item(...)
    ...

def _is_user_namespace(namespace: tuple[str, ...]) -> bool:
    return bool(namespace) and namespace[0] == "user"
```

Точка: только Select hot-path. Write / extract / MCP `search_memory` с явным user scope — не менять в этом PR (иначе расползание). Если MCP search тоже bleed’ит в UI — отдельный follow-up.

Опционально (тот же PR, +5 строк): метрика/лог `memory_recall.user_ns_fact_skipped` для observability (040) — не обязателен для зелёного A.2d.

---

## Тесты

| Тест | Ожидание после фикса |
|---|---|
| `test_p0_scratchpad_leak_to_attachment` (A.2d) | **PASS** — `_USER_NS_MARKER` / A2 filename нет в T1 hits; fence asserts уже OK |
| `test_recall_merges_user_namespace_preferences` | PASS — `kind=preference` остаётся |
| unit: user-ns `kind=fact` про файл не в bundle другого thread | добавить рядом с `test_memory_recall.py` (регрессия P0-B) |

Не править asserts A.2d «чтобы прошёл» — править Select.

---

## Вне scope этого PR

- `get_many(thread_id)` — P0-A  
- Scratchpad score 10000 — B.1 (by design pin)  
- Запрет extract писать attachment mentions в user-ns — полезный hardening Write, отдельный тикет  
- Org-namespace — оставить (wiki/entity); при bleed аналогично — kind allow-list позже  

---

## PR

**Ветка:** `fix/p0-recall-thread-scope`  
**Файлы:** `application/services/memory_recall.py` (+ опционально unit в `tests/unit/test_memory_recall.py`)  
**Гейт:** A.2d зелёный + prefs unit зелёный.
