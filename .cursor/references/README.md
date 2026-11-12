# Kimi references (Cursor SoT for agents)

Локальный индекс материалов Moonshot / Kimi для редизайна и разработки `web/`.
Норма продукта — правило [`.cursor/rules/kimi-design.mdc`](../rules/kimi-design.mdc);
runtime-токены — [`web/src/tokens.css`](../../web/src/tokens.css).

| Путь | Роль | В git? |
|------|------|--------|
| [`kimi-brand-book.md`](kimi-brand-book.md) | Курируемый текстовый экстракт Brand Book + маппинг на токены Palatium | да |
| [`kimi-widget-design-system.md`](kimi-widget-design-system.md) | Vendored visual discipline из `kimi-widget` (B/W first, accents last) | да |
| [`kimi-widget-icon-system.md`](kimi-widget-icon-system.md) | Vendored правила иконок `kimi-widget` (SVG-библиотека — в клоне) | да |
| [`awesome-kimi-k3-frontend-prompt/`](awesome-kimi-k3-frontend-prompt/) | Демо / промпты / ZIP-артефакты Kimi K3 — **inspiration only** | нет (gitignore) |
| [`../skills/kimi-skills/`](../skills/kimi-skills/) | Полная коллекция agent-skills Kimi (в т.ч. SVG icons) | нет (gitignore) |

## Иерархия источников (жёсткий порядок)

1. **Официальный Brand Book** — <https://www.kimi.ai/resources/kimi-brand> (внешний SoT).
2. **Этот каталог** / MCP `kimi-docs` (filesystem на `.cursor/references`).
3. **`web/src/tokens.css`** — единственные значения в коде.
4. **`kimi-widget-design-system.md`** (+ icon-system) — визуальная дисциплина виджетов; имена `--kimi-color-*` из iframe **маппить** на `tokens.css`, не копировать сырьём в SPA.
5. **`awesome-kimi-k3-frontend-prompt/`** — только идея/паттерн взаимодействия; UI в `web/` не копировать без сверки с п.1–3.

**Windows / MCP:** `kimi-docs` стартует через `.cursor/scripts/kimi-docs-mcp.cmd`
(подставляет `C:\nvm4w\nodejs` и др., затем `npx … server-filesystem`). После правки
`mcp.json` — Reload MCP в Cursor. Без MCP агент читает файлы этого каталога напрямую.

Оркестратор агента: скилл [`.cursor/skills/kimi-design/SKILL.md`](../skills/kimi-design/SKILL.md).
Полный план волн: [`.cursor/plans/kimi-full-redesign.md`](../plans/kimi-full-redesign.md).
Навигация для людей: [`docs/frontend/kimi-brand.md`](../../docs/frontend/kimi-brand.md).

**Product pages (отдельный слой):** [`docs/kimi-knowledge/INDEX.md`](../../docs/kimi-knowledge/INDEX.md)
— зеркало use-cases / capabilities / showcases; правило
[`kimi-product-knowledge.mdc`](../rules/kimi-product-knowledge.mdc). Не SoT для токенов UI.
