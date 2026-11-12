# Kimi answer formatting — visual density on ContentDocument

**Статус:** in progress (волны F0–F5).  
**Дата:** 2026-11-11.  
**Основание:** ADR 0005 (`ContentDocument` — единственный контент-контракт); Brand Book
Typography / Color; icon discipline — `.cursor/references/kimi-widget-icon-system.md`.  
Inspiration only (не SoT): `awesome-kimi-k3-frontend-prompt/`, `kimi-skills/kimi-widget`.

Дополняет (не переписывает): `docs/formatter-schema-first.md`,
`.cursor/plans/response-shapes.md`, `.cursor/plans/answer-quality-max-pro.md`.

## 1. Проблема

Контракт уже выражает Kimi-плотность (`heading.icon`, `kv`, `list.level`, `callout`),
но генерация и пост-политика её режут: один icon на lead heading, промпт «Use sparingly»,
`document_analysis` учит bold-list вместо `kv`, few-shot без analysis-примера,
`IconToken` = 18 имён.

## 2. Scope

- `IconToken` allow-list (~36–40) + FE glyphs + sync-тест.
- `PresentationIconPolicy`, `ShapeRecipePolicy`, content lint, mechanical kv-promote.
- Formatter prompts / few-shot.
- CSS polish KV / ThinkingTrace.
- Evals + метрика `palatium_formatter_icon_coverage`.

## 3. Вне scope

- Runtime Kimi Agent / CDN / iframe CSS names в SPA.
- Все 105 SVG из kimi-widget в answer chrome.
- Новый `ResponseShape` без доказанного mismatch.
- Отдельный LLM-канал «thought» как у Kimi reasoning.
- Копипаст из `awesome-kimi-k3-frontend-prompt/packages`.

## 4. DoD визуальной плотности

Sparse chrome (Big Tech, 2026-11-11): **lead heading only** получает icon
через `PresentationIconPolicy`; section H2/H3 без массового chrome.
Lint `missing_section_icons` — lead-only; dense examples — anti-pattern.

Для `response_shape=document_analysis` и `auto` при `meta.kind ∈ {analysis, report, guide}`:

| Критерий | Порог |
|---|---|
| Lead heading `icon != null` (после enrich) | 1 на документ (не все H2/H3) |
| ≥1 блок `kv` **или** (list + callout) | shape satisfied |
| Nested lists где есть подпункты | `ListItem.level` ≥ 1 |
| Emoji в прозе | 0 |
| Formal `letter`/`memo`/`response`/`faq` | без принудительного heading chrome |
| User Edit rewind | `POST …/turns/truncate` + FE composer restore |
| Regenerate rewind | truncate before prompting user + drop tail (no duplicate turns) |
| Answer Share | Web Share API → clipboard fallback (message + artifact) |

## 5. Метрики

| Сигнал | Владелец |
|---|---|
| `palatium_formatter_icon_coverage` (headings_with_icon / headings) | registry 040 |
| `palatium_content_lint_findings_total{rule=sparse_analysis_structure\|missing_section_icons}` | lint |
| `palatium_response_shape_total` для `document_analysis` | shape (уже есть) |

## 6. Волны

| Волна | Содержание | Статус |
|---|---|---|
| F0 | Эта speка | done |
| F1 | IconToken expansion + glyphs | done |
| F2 | Policy + lint + kv-promote | done |
| F3 | Prompt + few-shot | done |
| F4 | UI polish | done |
| F5 | Evals / smoke / metrics | done |

## 7. Enforcement

- Unit: IconToken ↔ `KIMI_TOKEN_GLYPHS` 1:1; PresentationIconPolicy; ShapeRecipe; lint; prompt examples validate.
- Live smoke: analysis → icons + kv.
- FE: `npm run verify` после glyph/CSS правок.
