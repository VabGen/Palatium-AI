# Kimi Brand Book (внешний SoT)

Официальный брендбук Moonshot / Kimi: визуальная идентичность для UI и
коммуникаций. **Источник истины — внешняя страница**, не этот файл и не
локальные клоны (086: ссылка, не пересказ).

- **Brand Book:** <https://www.kimi.ai/resources/kimi-brand>  
  (актуально на 2026-11-06)
- **Контакты по лицензии / партнёрствам:** `hi@moonshot.ai`
- **Legal:** `legal@moonshot.ai`
- **PR / media:** `globalpr@moonshot.ai`  
  В публичных материалах: *«Kimi — AI assistant developed by Moonshot AI»*.

## Зачем в этом репозитории

Ориентир при работе с фронтендом (`web/`) и правилом
[`.cursor/rules/kimi-design.mdc`](../../.cursor/rules/kimi-design.mdc).

**Решение 2026-11-06 (C):** чат `web/` переведён на палитру / зонирование Brand
Book. Runtime SoT — [`web/src/tokens.css`](../../web/src/tokens.css)
(`--kimi-*` + семантические `--bg` / `--accent`). 084 (качество, бюджет, a11y,
без CDN-шрифтов) остаётся в силе; меняется только визуальная идентичность.

Агентский оркестратор: [`.cursor/skills/kimi-design/SKILL.md`](../../.cursor/skills/kimi-design/SKILL.md).  
Локальный экстракт + индекс: [`.cursor/references/`](../../.cursor/references/README.md).  
**Полный план редизайна (волны K0–K5 + Track P):**  
[`.cursor/plans/kimi-full-redesign.md`](../../.cursor/plans/kimi-full-redesign.md).

**Шрифты (K2):** self-host Inter Variable + **Geist** (Brand «Display» = Vercel
Geist Sans, OFL) + Geist Mono в `web/public/fonts/` (лицензии рядом). Sentient
(Fontshare) — опциональный serif; пока системный fallback в `--font-serif`.
SPA — [`web/src/fonts.css`](../../web/src/fonts.css); виджет —
`injectKimiFonts()` + `widget-release` копирует `dist-widget/fonts/*` (не CDN, 084).  
MCP `kimi-docs` в [`.cursor/mcp.json`](../../.cursor/mcp.json) отдаёт filesystem на
`.cursor/references` (для агента в IDE). Лаунчер:
[`.cursor/scripts/kimi-docs-mcp.cmd`](../../.cursor/scripts/kimi-docs-mcp.cmd)
(подставляет Node/`nvm4w`). Без MCP агент читает `.cursor/references/*` напрямую.

**Product knowledge (не Brand):** публичные Resources / Use Cases / Capabilities /
Showcases зеркалятся в [`docs/kimi-knowledge/`](../kimi-knowledge/INDEX.md)
(`uv run python scripts/fetch_kimi_docs.py`). Правило агента —
[`.cursor/rules/kimi-product-knowledge.mdc`](../../.cursor/rules/kimi-product-knowledge.mdc).
Не смешивать с Color System / токенами.

## Разделы Brand Book (навигация)

| Раздел | Содержание |
|--------|------------|
| Starting Point | Позиционирование: tech rigor + humanism |
| Logo System | Геометрия и identity логотипа |
| Color System | Палитра вокруг brand blue, иерархия цветов |
| Typography & Layout | Inter + Geist Mono + Sentient; base / expressive grid |
| UI Upgrade | UX-принципы продукта Kimi (не контракт Palatium) |
| Brand Visual Assets | Generative / De-coding textures, wallpaper generator |
| Data Visualization | Минимализм, electric blue на нейтральных серых |
| Brand Reality | Физические носители |
| Film & Photography | Product / concept / tutorial / user stories |

Скриншоты, ассеты и генераторы — только на странице Brand Book; в git
репозитория не зеркалим (текстовый экстракт для агентов —
[`.cursor/references/kimi-brand-book.md`](../../.cursor/references/kimi-brand-book.md)).

## Локальные reference-клоны (gitignored)

Не часть продукта; не коммитить (см. корневой `.gitignore`):

- `.cursor/references/awesome-kimi-k3-frontend-prompt/`
- `.cursor/skills/kimi-skills/`
