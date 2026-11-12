# Kimi Brand Book — локальный экстракт для агентов

**Внешний SoT:** <https://www.kimi.ai/resources/kimi-brand> (актуально на 2026-11-06).  
Этот файл — **навигация + зафиксированные нормы**, уже принятые в Palatium (решение C).  
Ассеты / генераторы / скриншоты в git **не** зеркалим. При расхождении — побеждает внешняя страница, затем обновляем этот файл и `web/src/tokens.css` в одном изменении.

Лицензия / партнёрства: `hi@moonshot.ai` · Legal: `legal@moonshot.ai` · PR: `globalpr@moonshot.ai`.  
Публично: *«Kimi — AI assistant developed by Moonshot AI»*.

---

## Starting Point

- Позиционирование: tech rigor + humanism; curiosity / youthfulness как origin visual identity.
- Цель: consistent, clear, professional image across channels; trusted partner at innovation × aesthetics.

## Logo System

- Core geometry & identity: rational order + creative tension.
- Для продукта Palatium: не подменять логотип СЭД/host чужим mark без лицензии; brand blue и зонирование — да.

## Color System

Signature hierarchy вокруг brand blue. В коде Palatium — только токены из `web/src/tokens.css`:

| Brand role | Токен примитива | Hex (зафиксирован) |
|---|---|---|
| Dark canvas | `--kimi-obsidian` | `#0B0F19` |
| Light canvas / text on dark | `--kimi-pure-white` | `#F8FAFC` |
| Deep navy | `--kimi-brand-navy` | `#002F5B` |
| Signature accent | `--kimi-brand-blue` | `#007CFF` |
| Hover / info | `--kimi-brand-blue-bright` | `#00A1FF` |
| Soft fill | `--kimi-brand-blue-soft` | `#A0DAF7` |
| Warning / rare | `--kimi-amber` | `#D97706` |
| Ink on light | `--kimi-ink` | `#121212` |

Семантика продукта (`--bg`, `--accent`, `--text`, …) **алиасит** примитивы — сырой hex в компонентах запрещён (`kimi-design.mdc`).

Расширенная expressive-палитра (`--kimi-cyan`, `--kimi-lavender`, …) — только для data / редких акцентов, не как theme fill.

## Typography & Layout

Триада Brand Book:

- **Inter** — functional body / UI (`--font-body` / `--font-sans`)
- **Geist Mono** — developer precision (`--font-mono`)
- **Sentient** — literary warmth (`--font-serif`, опционально)
- **Geist (Sans) → Inter** — display (`--font-display`); Brand Book «Geist Display» =
  Vercel Geist OFL в Palatium
- **Sentient** — literary serif (`--font-serif`); Fontshare FFL — опционально

CDN / Google Fonts в виджет **не** подключаем (084). Self-host Inter + Geist + Geist Mono — DONE (K2).

**Grid:** base grid (математический ритм) + expressive grid (визуально-фокусные сценарии).

Spacing rhythm Palatium: `--space-1`…`--space-7` = 4 / 8 / 16 / 24 / 32 / 48 / 64 px.  
`ZONE_TOP` = 64px (`--zone-top-height`).

## UI Upgrade (продуктовые принципы Kimi — ориентир UX, не копипаст экранов)

- History / sidebar в зоне видимости; pin → Projects.
- Proactive surfaces: scheduled tasks, widgets, canvas — не только reactive chat.
- Bond / skills growth — «My Kimi» как метафора привычки (в Palatium: HITL/карточки, не клон UI).
- UI flows with conversation: warm canvas, living orb/centerpiece, glass on mobile — адаптировать через зоны `ZONE_*` и токены, не через чужой HTML.

## Brand Visual Assets

- Generative De-coding textures / wallpaper generator — только с официальной страницы.
- Organic digital textures: quiet immersive canvas; не шумные градиентные «AI blobs» как основной brand signal.

## Data Visualization

- Minimalism / reduction; accuracy first — no misleading distortion.
- Electric blue highlights on neutral grays for core metrics.
- Для inline widgets: см. `kimi-skills/skills/kimi-widget/references/design-system.md` (дисциплина B/W + accent last); **маппить** на `--kimi-*` / семантику `tokens.css`, не тащить iframe-имена (`--kimi-color-*`) в SPA без алиаса.

## Brand Reality / Film & Photography

- Physical touchpoints: structural rigor, minimal, enduring quality.
- Film poles: Product Feature · Concept · Tutorial · User Stories.
- Tone: curious, avant-garde, exploring — не «generic purple SaaS».

---

## Coordinate zoning (Palatium contract)

Обязательные зоны экрана (`data-zone`):

| Zone | Назначение |
|------|------------|
| `ZONE_TOP` | навигация, 64px |
| `ZONE_HERO` | empty-state / орб / главный акцент |
| `ZONE_BODY` | лента, артефакты |
| `ZONE_FOOTER` | composer / вторичные действия |

Анимация: только `transform` / `opacity`; `prefers-reduced-motion: reduce` обязателен.
