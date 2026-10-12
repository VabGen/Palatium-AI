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

- [ ] Один preview-путь; нет мерцания на done
- [ ] Иконки в preview через TokenIcon
- [ ] `<icon x="…"/>` не появляется как текст
- [ ] Leading-иконка в Paragraph не теряется
- [ ] Mid-text → strip + warn
- [ ] Unknown → fallback + warn
- [ ] Промпт требует `name=`
- [ ] Тесты / ruff / mypy / eslint чистые

## Запрещено

- Путь A (`:icon[]`) / путь B (rehype)
- Ломать `ContentDocument` → `BlockRenderer`
