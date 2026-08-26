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
