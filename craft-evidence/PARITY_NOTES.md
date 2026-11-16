# Palatium vs kimi parity evidence (2026-11-09)

## Sources
- Playwright logged-in kimi.ai (product shell) @ 1440x900
- Playwright local http://127.0.0.1:5174/standalone.html
- Craft CLI `web_site_open` → evidence `ev_9b1b4a2c…` (signed-out marketing; private profile)
- Craft MCP `enable_toolset browser` left namespace in error — CLI used for open

## Observed (kimi product)
- Sidebar 240px; header logo 32 + expand 32; New chat 224x42, border 1px 13% black, r12
- Home doodle: `.home-banner img` 400x82 (natural 800x160) data PNG
- Composer `.chat-input` ~766px; tray `.input-options-tray-items` ~728px
- Tray copy EN: Choose project / Plugins / Use desktop app + Limited-time offer
- Rail EN short labels: Scheduled, Docs, Sheets, Build

## Bugs fixed this pass
1. Capsule width: home `#chat-box` centers children → capsule shrank to ~453px (kimi 768). CSS now forces `width:100%` on capsule inside `#chat-box`.
2. React warning: `make3d` glyph props `stroke-width` → `strokeWidth` camelCase.
3. Tray copy: `composer.bar.computer` → Use desktop app / Использовать приложение.
4. EN rail labels aligned to kimi short forms.

## Fixed next pass
5. Desktop fold: sidebar `width:0` + `aria-hidden`; stage `.sidebar-main-trigger` + Ctrl+B tip (kimi `.sidebar-main-trigger` @ 17,17 / 32×32).
6. Hero doodle: original SVG 400×82 (`BrandWordmark`) — Typography display + brand-blue stroke (not kimi PNG).

## Fixed next pass (beard / chips / skill clear)
7. Landing tray beard: `::before` on `.composer-capsule__bar--tray` — `--kimi-bg-secondary-90` + `blur(15px)`, r0 0 24 (kimi `.input-options-tray::before`).
8. Product chip gap: removed erroneous `margin-right: 90px` → 12px track gap (measured kimi 12).
9. Product skill dismiss: composer chip uses X + `onExitProductMode` → home (parity with Deep Research chip).
10. Project menu: Addfolder / Nofolder glyphs; divider only when projects exist.
11. Hover: Fills-F1 wash on chrome buttons; collapse/expand toggle chevron enter on hover.
12. Folder / monitor stroke glyphs tightened.

## Product cuts (not kimi parity)
13. Removed tray «Use desktop app», header «Upgrade plan», sidebar Invite/Upgrade/Get App, settings subscription/billing/gift-cards.
14. Chip hover: icon enter animation (no translateY lift). Manage plugins = Switch glyph. Send arrow stays white on solid hover.
15. Project menu: filled Addfolder / Nofolder (kimi iconify).

## Fixed next pass (send + project chain)
16. Send idle = `--kimi-gray-e1` soft chip; after input = Labels-Primary black (tone solid/soft).
17. «Новый проект» → `#/project/create` page → Create → `#/project/{id}` workspace
    (Instructions / Files modals). Sidebar project row opens workspace. Local fallback
    when `/projects` 404 in standalone.
18. Composer attachments: cards inside white editor (not above); grey tile + icon +
    stem/`EXT size` + corner X + dark caret tooltip (kimi file-add flow).
19. Product cut: removed 3D Make / Build / Design / Work / Code / Open Platform from
    sidebar + home chips; deep links map to home.
20. Craft Anything brief: «Выбрать проект» full chain — tray menu select stays home;
    New → `/project/create?project_create_from=project_selector_new`; Create → workspace;
    workspace/sidebar More = Edit / Pin to top / Delete. Palatium now wires rename/pin/delete
    (+ DELETE `/projects/{id}`).

## Still open
- Craft MCP browser toolset enable lists tools but catalog refresh still Essentials-only;
  live kimi observed via cursor-ide-browser.
- `/api/projects` 404 in standalone without backend (expected; create/rename/delete local fallback).
