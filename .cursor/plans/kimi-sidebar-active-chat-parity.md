# План: sidebar + active-chat parity (после Craft/Playwright evidence)

Обновлено: 2026-11-09.  
SoT UI: Brand Book + `tokens.css` (не копипаст HTML kimi.ai).  
Evidence: Craft CLI `web_site_open` → evidence `ev_9b1b4a2c…`; Playwright logged-in session (home + `/chat/…`).

## Craft status

| Путь | Результат |
|---|---|
| MCP `web_site_open` | `consent_required` (Cursor MCP ещё не перечитал `ask_before_running=false`) |
| CLI `craft-anything-cli web-site-open` | OK, opened kimi.ai 1440×900 |
| CLI `web-site-capture` отдельной командой | fail: каждый CLI-вызов = свой browser; capture нужен в одной MCP-сессии |

**Действие пользователя:** перезапустить Cursor (или MCP craft-anything), чтобы MCP подхватил `ask_before_running=false` из `%APPDATA%\craft-anything\config.toml`.

## Observed on kimi.ai

### Sidebar (ZONE_NAV)

- Header: K-mark + collapse; **New chat** + `Ctrl K`.
- Primary rail: My Kimi, Plugins, Scheduled, Inspiration, Docs, Sheets, Kimi Code, Kimi Claw (+ Add Claw), Deep Research; overflow: Open Platform, Kimi Work, Slides, **3D Make [New]**, Build, **Design [Beta]**.
- Projects (collapsible) + New project.
- Chats + All chats + thread list with ⋯.
- Footer: Invite to Earn card; profile + **Upgrade** + Get App.

### Active chat

- Top: minimal — thread title control + share (не полный chrome home).
- Transcript: user pills right; assistant plain; action row (regenerate / copy / feedback).
- Composer **без** tray (нет Choose project / Plugins / desktop app) и **без** publisher chips.
- Capsule: placeholder, Instant/High, mic, send — floating bottom.

### Home (для контраста)

- Tray: Choose project + Plugins + **Use desktop app ↔ Limited-time offer**.
- Publisher shortcuts row + Explore inspiration.
- Wordmark = **Kimi Doodle** image (не plain text).

## Gaps vs Palatium `web/`

| # | Gap | Ours | Priority |
|---|---|---|---|
| A1 | Badges **New** / **Beta** on rail items | нет | P1 |
| A2 | K-mark / brand glyph in sidebar header | нет (только collapse + New chat) | P2 |
| A3 | Project rows clickable / filter shelf | display-only | P2 |
| A4 | Thread rename/delete wired | `comingSoon` toasts | P2 |
| A5 | Invite visible when rail collapsed | hidden when collapsed | P3 |
| B1 | Active composer: confirm tray stays **off** (matches kimi) | уже `showToolBar={messages.length===0}` | done / keep |
| B2 | Active top bar denser (share working; fewer stubs) | share/attach/more stubs | P1 |
| B3 | Message action row (regen/copy/feedback) parity | частично | P1 |
| B4 | Home wordmark = doodle/animated asset (tokens/SVG) | text wordmark + idle | P2 |
| B5 | Tray label: **Use desktop app** + offer (we wired computer+offer) | `composer.bar.computer` | P3 copy |
| B6 | `ComposerModePills` mount | не на home (ok); проверить in-chat kimi — на active **не** видно | skip unless product asks |

## Next wave (recommended order)

1. **B2 + B3** — active chat chrome (top actions + message actions) without inventing tray.
2. **A1** — New/Beta badges on rail (i18n + token chip).
3. **B4** — hero doodle treatment under Brand Visual Assets / our SVG.
4. **A3/A4** — project open + thread mutations (needs backend/HITL where write).

## Constraints

- Только `var(--…)` из `tokens.css`; zones `ZONE_*`.
- Не копировать HTML/CSS с kimi.ai CDN.
- Motion: transform/opacity + `prefers-reduced-motion`.

## DoD волны

- Active chat visual checklist vs screenshot (no tray; slim top; message actions).
- Sidebar badges New/Beta на 3D/Design (или наш продуктовый аналог).
- `npm run verify` в `web/`.
