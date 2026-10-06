# Palatium Chat UI

React + Vite shell that renders `ContentDocument` blocks from `POST /api/intents/process`.

## Dev

```powershell
# API on :8000
poetry run python -m palatium_ai.main

# UI with proxy
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173/ui/

## Production-ish (served by FastAPI)

```powershell
cd web
npm run build
poetry run python -m palatium_ai.main
```

Open http://127.0.0.1:8000/ui/

## Checks

```powershell
cd web
npm run verify          # typecheck + lint (0 warnings) + prettier + unit/integration tests
npm run test            # Vitest only (tests/unit, tests/integration)
npm run test:e2e        # Playwright + axe against standalone.html (no backend needed)
npm run build:widget    # builds dist-widget + release.json (fails if the gzip budget is blown)
```

`npm run verify` is the same aggregate CI runs in the `frontend` job. Quality gate rules
(types, tests pyramid, a11y, bundle budget) live in `.cursor/rules/084-frontend-quality.mdc`.
