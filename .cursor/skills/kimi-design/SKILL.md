---
name: kimi-design
description: >
  Оркестратор полного соответствия Kimi Brand Book при редизайне и разработке UI
  в web/. Читай ПЕРЕД любым новым экраном, компонентом, токеном или стилем чата /
  виджета. Маршрутизирует к Brand Book, tokens.css, kimi-widget и web-craft;
  запрещает копипаст из awesome-kimi демо без сверки.
---

# Kimi Design — оркестратор соответствия

Используй этот скилл при: полном редизайне `web/`, добавлении экранов/функций UI,
правке стилей, empty-state, composer, thinking orb, карточек HITL, data viz в чате.

## Иерархия SoT (не нарушать)

1. Официальный Brand Book: <https://www.kimi.ai/resources/kimi-brand>  
   (WebFetch / браузер; при недоступности — локальный экстракт ниже.)
2. Локальный экстракт: `.cursor/references/kimi-brand-book.md`
3. Правило: `.cursor/rules/kimi-design.mdc` (alwaysApply на `*.tsx/css`)
4. Runtime значения: `web/src/tokens.css` (+ семантика в `web/src/styles.css` только через `var(--…)`)
5. Виджетная дисциплина (философия, не имена iframe-токенов):  
   `.cursor/references/kimi-widget-design-system.md`  
   (+ `.cursor/references/kimi-widget-icon-system.md` при иконках; SVG assets — в клоне `kimi-skills`)
6. Motion / полировка: `.cursor/skills/web-craft/SKILL.md` → `animate` / `emil-design-eng`  
   **после** выбора токенов Kimi; `apple-design` не перебивает Color System Kimi.

Inspiration only (не SoT продукта):

- `.cursor/references/awesome-kimi-k3-frontend-prompt/` — промпты и демо K3
- остальные `.cursor/skills/kimi-skills/skills/*` — по задаче (см. таблицу)

MCP `kimi-docs` монтирует `.cursor/references` (filesystem). Индекс: `.cursor/references/README.md`.
План волн (K0–K5 visual, P1–P5 product): `.cursor/plans/kimi-full-redesign.md`.

## Обязательный workflow перед кодом

1. Назвать аспект: logo · color · typography · layout/zones · data viz · motion · copy tone.
2. Открыть соответствующий раздел Brand Book (URL или `kimi-brand-book.md`).
3. В ответе явно указать раздел (*«Согласно разделу Color System, …»*).
4. Сверить с существующими токенами в `tokens.css`. Нет токена → предложить добавить примитив `--kimi-*` + семантический алиас; **не** писать сырой hex в компоненте.
5. Разметить зоны `data-zone="ZONE_*"`; не смешивать TOP/HERO/BODY/FOOTER без причины.
6. Анимация: только `transform`/`opacity` + `prefers-reduced-motion` (084).

## Стыковка с kimi-skills (выборочно)

| Задача | Скилл под `.cursor/skills/kimi-skills/skills/` |
|--------|-----------------------------------------------|
| Inline visual в ответе / контракт виджета | `kimi-widget` (+ его `references/`) |
| Слайды / PPTX в стиле Kimi tooling | `kimi-slides` |
| Поиск нужного скилла в коллекции | `kimi-find-skills` / `kimi-skills-finder` |
| Лендинг / marketing surface | `landing-page-scaffold` — затем всё равно Brand Book + tokens |
| Извлечение DS с референс-скринов | `design-system-builder` / `ui-blueprint` — выход сверять с Brand Book, не подменять его |

Не тащи в `web/` runtime Kimi Agent (CDN, iframe CSS variables names) без маппинга на `tokens.css`.

## Запрещено

- Копипаст HTML/CSS из `awesome-kimi-k3-frontend-prompt/packages` или чужих демо в продукт.
- Сырой hex / hardcoded font stacks в TSX/CSS компонентов.
- Подмена Brand Book эстетикой `apple-design` или «generic purple AI».
- Дублировать норму из `kimi-design.mdc` в новых markdown «на всякий случай» (050).

## Чеклист PR (фронт под Kimi)

- [ ] Раздел Brand Book назван в описании / ответе агента
- [ ] Только `var(--…)` из `tokens.css`
- [ ] Зоны `ZONE_*` на крупных поверхностях
- [ ] Motion GPU-only + reduced-motion
- [ ] `npm run verify` в `web/` (084)
