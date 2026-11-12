# План: полный визуальный клон каркаса Kimi в `web/`

Обновлено: 2026-11-06 (rev 3).  
Статус: **superseded for product chrome** by plan `kimi_product_parity` (light shell + Palatium, marketplace UI). K0–K5 below remain historical shell foundation.  
Track V + P1b + P2 + mode→intent DONE; backlog Track P: P3b/P4.  
Внешний SoT: <https://www.kimi.ai/resources/kimi-brand>  
Локальный agent SoT: [`.cursor/references/`](../references/README.md) · оркестратор [`.cursor/skills/kimi-design/SKILL.md`](../skills/kimi-design/SKILL.md).

Связанные: [web-embed-assistant.md](./web-embed-assistant.md), [docs/frontend/kimi-brand.md](../../docs/frontend/kimi-brand.md), 084 / 005 / 050.

---

## 0. Проблема

Нужен **полный визуальный клон каркаса** kimi.ai (Sidebar + Main Chat + Composer), а не только рескин токенов существующей узкой колонки. K0/агентский SoT и K1 (hex→tokens) — фундамент; дальше — оболочка как у продукта Kimi.

---

## 1. Зафиксированные решения (defaults)

| Решение | Выбор | Основание |
|---|---|---|
| Цель Track V | **Visual clone каркаса** (Sidebar history + stage + composer modes/dropdowns) | Утверждение владельца 2026-11-06 |
| Тема по умолчанию | **dark** (Obsidian); light — parity | embed/СЭД |
| Шрифты K2 | Self-host Inter + Geist Mono (утверждено); Display/Sentient — после лицензии | 084, бюджет 224 KiB |
| Бюджет | **224 KiB gzip** утверждён | widget-release |
| Dropdown surface | `--kimi-surface-elevated` + `--kimi-border` (алиасы семантики) | Color System |
| Иконки chrome | Inline SVG stroke **1.5px**, без новых icon-библиотек для сайдбара/меню/pills | K5 + частично K3 |
| Track P | Только **сложная логика**: backend Projects, внешние API, durable history | UI history shelf = K3 |

Отвергнуто: откладывать sidebar до после K5; CDN fonts; копипаст awesome-kimi ZIP.

---

## 2. Scope / вне scope

### В scope Track V (K0–K5)

- Токены + hex-гейт (K1).
- Self-host fonts (K2).
- **K3 полный каркас:** `ZONE_NAV` (History shelf) + `ZONE_TOP` + `ZONE_BODY`/`ZONE_HERO` + `ZONE_FOOTER`; dropdowns (модель, профиль/настройки); mode pills Web Search / Deep Think / Agent; простые inline widget surfaces (эскиз в stage, без backend).
- K4 motion: в т.ч. dropdown `opacity` + `translateY`.
- K5: обязательные минималистичные SVG для sidebar/composer/меню (1.5px); viz tokens.

### Вне scope / Track P only

- Durable thread sync с host/backend, Pin/Projects API, внешние search/agent backends, EDMS Track II.
- Копипаст HTML из awesome-kimi packages.

---

## 3. Иерархия SoT (агент)

Brand Book URL → `.cursor/references/` → `kimi-design.mdc` → `tokens.css` → skill `kimi-design` → код → `web-craft` (motion после токенов).

---

## 4. Track V — волны

### K0 — Agent SoT (DONE 2026-11-06)

Rule, skill, references, MCP `kimi-docs`, vendored widget DS.

### K1 — Token hygiene (DONE 2026-11-06; дополнено aliases)

**Brand Book:** Color System.

- Hex только в `tokens.css`; `npm run check:kimi-hex` в `verify`.
- Продуктовые алиасы для chrome:
  - `--kimi-surface-elevated` → elevated / popover surface
  - `--kimi-border` → hairline border (`--stroke` / strong по контексту)
- DoD: verify + нет сырого hex вне tokens.

### K2 — Typography self-host (утверждено, после K3 в очереди исполнения владельца: K1→K3 first)

**Brand Book:** Typography & Layout. Inter + Geist Mono self-host; Display/Sentient — K2b.

### K3 — Full shell (Sidebar + Main + Composer)  ← **включает бывш. P1 + часть P3**

**Brand Book:** UI Upgrade (History in plain sight) + Typography & Layout + Color System.

| Зона | Содержание |
|---|---|
| `ZONE_NAV` | History shelf / thread list, New chat, collapse; профиль внизу |
| `ZONE_TOP` | Title / model cue / collapse; **profile dropdown** (settings) |
| `ZONE_HERO` / `ZONE_BODY` | Empty + transcript + artifact; место под simple widget chrome |
| `ZONE_FOOTER` | Composer + **mode pills** (Web Search, Deep Think, Agent) + **model dropdown** + attach/send |

Dropdowns: фон `var(--kimi-surface-elevated)`, рамка `var(--kimi-border)`; рабочие в UI (локальный state; без backend).  
Mode pills: взаимоисключающий выбор режима в UI (флаги для будущей проводки в intent — Track P/backend).  
History: in-memory shelf (session); durable sync — Track P.

DoD: на `standalone` виден полный каркас как у Kimi; zones размечены; hex-гейт зелёный; unit на sidebar/pills/dropdown.

### K4 — Motion

Orb/press + **dropdown enter**: `opacity` + `transform: translateY(...)` only; `prefers-reduced-motion`.

### K5 — Icons & viz

Обязательные SVG 1.5px для sidebar, composer, menus (не lucide для этого chrome). Charts — viz tokens.

---

## 5. Track P — только сложная логика

| ID | Тема |
|---|---|
| P2 | Pin / Projects **backend** — **DONE 2026-11-06** (`projects` RLS + `sessions.project_id` + sidebar/composer) |
| P3b | Canvas / proactive widgets **с данными и API** (UI-эскиз уже в K3) |
| P4 | Bond / skills growth product logic |
| P1b | Durable / host-synced thread history — **DONE 2026-11-06** (`listSessions` → shelf; `switchThread` + turns hydrate) |
| P5 | Mobile densification polish после стабилизации каркаса — **DONE 2026-11-06** |

---

## 6. Enforcement

| Гейт | Где |
|---|---|
| `check:kimi-hex` + `npm run verify` | `web/` |
| Budget 224 KiB | `build:widget` |
| E2E a11y | Playwright |
| Zones `data-zone` | ревью + unit |

---

## 7. Статус

| Волна | Состояние |
|---|---|
| K0 | DONE 2026-11-06 |
| K1 | DONE 2026-11-06 (+ surface/border aliases в rev 2) |
| K2a | DONE 2026-11-06 (Inter Variable + Geist Mono self-host; companion `/fonts`) |
| K2b | DONE 2026-11-06 (Geist Sans OFL as Brand Display; Sentient — serif fallback, Fontshare optional) |
| K3 Full shell | DONE 2026-11-06 (Sidebar + pills + dropdowns; in-memory history) |
| K4 | DONE 2026-11-06 (dropdown translateY/opacity; pill press; reduced-motion) |
| K5 | DONE 2026-11-06 (kimiStroke 1.5px chrome; lucide only TokenIcon content map) |
| P5 | DONE 2026-11-06 (glass off-canvas nav ≤720px; denser composer) |
| P1b | DONE 2026-11-06 (GET /sessions shelf + switchThread) |
| Mode→intent | DONE 2026-11-06 (`composer_mode` API + ComposerModePolicy) |
| P2 | DONE 2026-11-06 (projects table + pin session + HistorySidebar/composer select) |
| Track P (остальное) | backlog (P3b/P4) |

---

## 8. Порядок исполнения (rev 2)

1. K1 aliases (surface/border) — сразу  
2. **K3 Full shell** — сразу после K1 (не ждать K2)  
3. K2 fonts  
4. K4 motion (dropdown Y/opacity)  
5. K5 SVG discipline  

---

## 9. Открытые вопросы

| # | Вопрос | Статус |
|---|---|---|
| 1 | Лицензия Geist Display / Sentient | Geist = OFL DONE; Sentient Fontshare optional |
| 2 | Default light для СЭД? | open; default dark |
| 3 | Проводка mode pills → backend flags | DONE 2026-11-06 (`composer_mode` → ComposerModePolicy) |

---

## 10. Запрещено

- Сырой hex вне tokens; CDN fonts; awesome-kimi copy-paste; icon packs для нового chrome; перенос backend Projects в K3.
