# Kimi Product Knowledge Base

Локальное зеркало публичных страниц kimi.ai (Resources / Use Cases / Capabilities /
Showcases) для агентов Cursor. **Не** заменяет Brand Book и runtime-токены.

| Слой | Путь | Роль |
|------|------|------|
| Product copy / capabilities | `docs/kimi-knowledge/**` (этот каталог) | Что умеет продукт Kimi |
| Brand / UI | `.cursor/rules/kimi-design.mdc` + `web/src/tokens.css` | Как выглядит UI |
| Brand extract | `.cursor/references/kimi-brand-book.md` | Color / type / logo |

Обновить зеркало: `uv run python scripts/fetch_kimi_docs.py --force`  
(или `bash scripts/fetch-kimi-docs.sh`). Правило агента:
[`.cursor/rules/kimi-product-knowledge.mdc`](../../.cursor/rules/kimi-product-knowledge.mdc).

Внешний SoT остаётся на https://www.kimi.ai/ — локальные `.md` могут устареть;
`fetched_at` в frontmatter каждой страницы.

## Resources (теория и архитектура)

- `resources/ai-agent.md` — отличие агента от чат-бота, базовые принципы.
- `resources/multi-agent.md` — оркестрация, роли агентов, архитектура.
- `resources/parallel-agent.md` — параллельные агенты, изоляция состояния, синтез.
- `resources/vibe-coding.md` — вайб-кодинг, примеры промптов.
- `resources/landing-pages.md` — как строить лендинги.
- `resources/poster.md` — создание постеров.
- `resources/business-proposal.md` — генерация бизнес-предложений.

## Use Cases (сценарии)

- `use-cases/mvp-builder.md` — создание MVP.
- `use-cases/portfolio-site-builder.md` — портфолио.
- `use-cases/blog-site-creator.md` — блоги.
- `use-cases/academic-research.md` — академические исследования.
- `use-cases/market-research.md` — маркетинговые исследования.
- `use-cases/resume-maker.md` — резюме.
- `use-cases/brochure-creator.md` — брошюры.

## Capabilities (функциональные возможности)

- `capabilities/landing-page-generator.md` — генератор лендингов.
- `capabilities/image-to-website.md` — изображение → сайт.
- `capabilities/document-generator.md` — Kimi Docs (LaTeX, длинные документы).
- `capabilities/pdf-to-ppt.md` — Kimi Slides (PDF → PPTX).
- `capabilities/translate-pdf.md` — перевод PDF/Word/Excel.
- `capabilities/python-code-gen.md` — генерация Python-кода.
- `capabilities/cpp-code-gen.md` — генерация C++ кода.

## Showcases (визуальные референсы и примеры)

- `showcases/websites-agent.md` — примеры сайтов и лендингов.
- `showcases/agent-swarm.md` — мультиагентные воркфлоу.
- `showcases/deep-research.md` — исследования с цитатами.
- `showcases/slides.md` — презентации.
- `showcases/sheets.md` — таблицы и дашборды.
- `showcases/docs.md` — документы.
- `showcases/design.md` — постеры и дизайн.
