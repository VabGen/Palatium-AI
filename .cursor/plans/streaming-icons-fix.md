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

## Follow-up (2026-10-30) — движение, семантика и дефект Lottie-ассетов

Волна закрыла класс багов §0 п.3 (скачок иконок) и добавила требования, которых
в исходном runbook не было. Раздел дописан, история выше не переписана (005).

### F1 — Семантическая деривация (закрыто)

`web/src/icons/semanticIcons.ts`: `iconForTone`, `iconForStepStatus`,
`iconForActionKind`. Деривация — только запасной путь: приоритет у явного поля
(`block.icon ?? iconForTone(block.tone)`, `option.icon ?? iconForActionKind(...)`).
Иначе контракт формы (иконку выбрал LLM) молча проигрывал бы деривации, и ответ
менялся бы «на глаз», а не по данным.

DoD: unit-тесты на каждое соответствие + на приоритет override'а.

### F2 — `prefers-reduced-motion` (закрыто)

Lottie-web крутит свой rAF-цикл, поэтому `.icon-animated { animation: none }`
гасит только Lucide-фоллбек. При выключенном движении Lottie не монтируется
вообще: рендерится статичный Lucide-глиф (WCAG 2.2.2). Приостановленный Lottie
(`autoplay={false}`) сознательно отвергнут — библиотека без автостарта не
рисует ни одного кадра, и статус исчезал бы целиком.

Отдельно: статусная анимация не циклична (`loop={false}`) — иконка автостартует,
поэтому бесконечное движение рядом с читаемым текстом под тем же запретом.

### F3 — Дефект Lottie-ассетов (закрыто)

Наблюдалось в Chromium (`lottie-web` light, кадр 15): **ни один** из
`web/src/lottie/{info,success,warning,danger}.json` не давал пригодного глифа.

| Файл | Было |
|---|---|
| `info.json` | `<path>` без `d`, группа `display: none` — не рисовалось ничего |
| `success/warning/danger.json` | path есть, но слой получал `matrix(-9999.99,0,0,-9999.99,50,50)` |

Причина — **формат кейфреймов**. Анимированное свойство было записано как
`{"t": 0, "s": […]}`: без temporal easing. `lottie-web` не интерполирует такой
кейфрейм → `NaN` → вырожденная матрица (`scale`) или `opacity = 0` со скрытием
группы. Проверено перебором форматов в Chromium:

| Формат | Результат |
|---|---|
| `s` без easing | `matrix(-9999.99…)` / `display: none` |
| legacy `s` + `e` (end value) | то же — в light-сборке 5.x не работает |
| `s` + `i`/`o` (temporal easing) | корректная интерполяция |

Поэтому easing добавлен во все ключевые кадры, кроме последнего (он задаёт только
точку остановки). Значения и цвета сохранены как были — это починка формата, а не
редизайн. `info.json` анимирует прозрачность, остальные — масштаб; оба свойства
после правки интерполируются (проверено по кадрам 0/7/15/22).

Гейт от рецидива: `web/tests/unit/lottie-assets.test.ts` требует `i`/`o` на каждом
интерполируемом кейфрейме и конечные значения в осмысленном диапазоне;
`web/e2e/icons-lottie.spec.ts` проверяет в реальном браузере, что контур нарисован,
группа не скрыта, `transform` не вырожден и кадры меняются. jsdom этого не умеет
(SVG не считается), поэтому нужны оба уровня.

### F5 — Анимация не запускалась вообще (закрыто)

Отдельный дефект, найденный при починке F3: в `lottie-react` **`autoplay`
по умолчанию `false`**. Компонент передавал только `loop`, поэтому библиотека
рисовала первый кадр и останавливалась — иконка была «анимированной» только по
имени (это же объясняет, почему контрольный E2E «кадры меняются» падал даже на
исправных ассетах).

Исправлено: `autoplay={!reduceMotion}` передан явно, с комментарием о дефолте
библиотеки. При `prefers-reduced-motion` Lottie не монтируется вовсе (F2), так что
явный флаг не конфликтует с гейтом.

Открытый вопрос (снят): нужны ли отдельные `check/x/clock/shield.json` — пока
используются приближения (`check→success`, `x→danger`, `clock→info`,
`shield→info`). Решение владельца: переэкспорт не заказываем, приближения остаются.

### F4 — Одинаковые иконки в перечне (закрыто)

Симптом: список из 9 компонентов отрисовался как timeline, у **каждой** строки
была одна и та же иконка часов.

Причина — контракт врал о состоянии процесса:

1. парсер Markdown превращал любой нумерованный список с `**Заголовок:**` в
   `StepsBlock` и **проставлял каждому шагу `status="pending"`**;
2. `StepItem.status` имел default `pending` — то есть отсутствие статуса
   трактовалось как «ещё не начато»;
3. во фронте маркер шага рисовал иконку **статуса**:
   `iconForStepStatus('pending') = 'clock'` → девять одинаковых часов.

Ось перепутана: иконка шага отвечает за состояние процесса, а не за тему пункта.
Лечение (не патч под конкретный документ):

- `StepItem.status: StepStatus | None = None` — отсутствие статуса ≠ «в работе»;
- парсер статус не выдумывает (`StepItem(title=…, body=…)`);
- `iconForStepStatus(null|undefined) → null`, и маркер рисует **порядковый
  номер** — единственный факт, который есть в данных;
- экспорт PDF не печатает `(None)`, если статуса нет;
- промпты: параллельные пункты (компоненты, опции) — список, не процесс;
  `status` — только реальный прогресс из входа (бюджеты промптов не подняты:
  текст сжат, `1894/1900` и `1992/2000`).

Открытый вопрос: миграции/снапшоты, где `status` был обязательным, теперь
получают `null`; старые документы в БД с `status="pending"` остаются валидными
и по-прежнему показывают часы — это корректно, статус в них действительно был
записан.

## Запрещено

- Путь A (`:icon[]`) / путь B (rehype)
- Ломать `ContentDocument` → `BlockRenderer`


