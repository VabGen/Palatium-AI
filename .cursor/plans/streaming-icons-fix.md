# Runbook: стриминг + рендеринг иконок (Path C)

**Ветка:** `master`  
**Приоритет:** 000/017/020/035/060/070/075/080 побеждают этот runbook.  
**Scope:** только стриминг сообщений и рендеринг иконок. Не расширять.  
**Путь:** **C** — не A (`:icon[]`), не B (rehype). Контракт остаётся `<icon name="…"/>` + `ContentDocument` → `BlockRenderer`.

---

## 0. Проблема

1. **Мерцание.** `text_delta` → markdown, `answer_delta` → `<p>`; на `done` preview сбрасывается, монтируется другой узел.
2. **Сырой тег.** `<icon x="…"/>` не ловится regex'ом (`name=` only).
3. **Скачок иконок.** Preview strip'ает токены; финал рисует через `TokenIcon`.

---

## Задачи (строго сверху вниз, коммит после каждой)

### ЗАДАЧА 1 — Один preview-путь (P0)
Файл: `web/src/components/ChatShell.tsx`

- Всегда `StreamMarkdownPreview` для всех дельт.
- Убрать ветку `<p className="stream-preview">`.
- Стабильный key pending-пузыря; плавный transition preview → BlockRenderer.

```
fix(web): single-path StreamMarkdownPreview for all streaming deltas
```

### ЗАДАЧА 2 — Иконки в preview (P0)
Файлы: `StreamMarkdownPreview.tsx`, `web/src/lib/markdown.ts`

- Рендерить иконки через `TokenIcon`, не strip.
- Расширить regex для `x=` там, где sanitize ещё нужен.

```
fix(web): render icon tokens in stream preview via TokenIcon (no strip)
```

### ЗАДАЧА 3 — Sanitizer / parser (P0)
Файлы: `icon_sanitizer.py`, `markdown_parser.py`

- Regex: `name=` и `x=` → нормализация к `name=`; warn + turn_id при `x=`.
- Paragraph: сохранять leading-icon.
- Mid-text: strip (+ warn), не оставлять как текст.

```
fix(formatter): accept x= in icon sanitizer; preserve paragraph leading icons
```

### ЗАДАЧА 4 — Промпт (P1)
Файл: `formatter/prompts.py`

- Явно: attribute MUST be `name`, example `<icon name="check"/>`.

```
fix(formatter): explicit attribute-name rule in icons prompt
```

### ЗАДАЧА 5 — Fallback (P1)
Файл: `web/src/icons/TokenIcon.tsx`

- Unknown → default icon + `console.warn({name, turnId})`.

```
fix(web): graceful fallback for unknown icon names
```

### ЗАДАЧА 6 — Тесты (P1)

```
test(web): streaming stability + icon normalization
```

---

## DoD

- [x] Один preview-путь; нет мерцания на done
- [x] Иконки в preview через TokenIcon
- [x] `<icon x="…"/>` не появляется как текст
- [x] Leading-иконка в Paragraph не теряется
- [x] Mid-text → strip + warn
- [x] Unknown → fallback + warn
- [x] Промпт требует `name=`
- [x] Тесты unit (web+py) зелёные; ruff/eslint на затронутых файлах чистые
  (полный mypy / e2e playwright — прогон на CI / локально по желанию)

## Follow-up (2026-10-13) — закрыто в `fix_chat_readability`

Ранее DoD «иконки в preview» был выполнен только на FE; BE всё ещё strip'ал
`<icon/>` из SSE. Дополнительно: dual-emit `replace` обнулял `textAccumulated`,
неполный `<icon` утекал как `name="…"/>`, orphan-иконки и `1 1 1 1`.
Исправления — план `.cursor/plans/fix_chat_readability_*.plan.md` (не
переписывать историю выше).

## Запрещено

- Путь A (`:icon[]`) / путь B (rehype)
- Ломать `ContentDocument` → `BlockRenderer`
