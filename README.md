<div align="center">

# 🏛️ Palatium AI

### Production-grade multi-agent platform for corporate assistants

**LangGraph orchestration · MCP tools · Zero Trust · HITL · LiteLLM**

<br/>

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](docs/docker.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](src/palatium_ai/LICENSE)

<br/>

[📖 Полный гайд](docs/handbook.md) ·
[🐳 Docker](docs/docker.md) ·
[🔐 Секреты](docs/secrets.md) ·
[📚 Docs index](docs/README.md)

</div>

---

## ✨ Что это

**Palatium AI** — не чат-виджет и не «ещё один RAG-скрипт».  
Это **платформа**, на которой собирают управляемых AI-ассистентов для офиса и enterprise:

| | |
|---|---|
| 🧠 **Multi-agent pipeline** | Intent → Supervisor → Context → Worker → Critic → Formatter |
| 🔌 **MCP tools** | Единый протокол к СЭД, analytics и другим системам |
| 🛡️ **Zero Trust + HITL** | RBAC allow-list, confidence gates, `requires_review` |
| 🧩 **Clean / Hex architecture** | Domain → Application → Infrastructure → API |
| ⚡ **LiteLLM** | Один контракт на OpenAI, Anthropic, Ollama, Qwen… |

> Цель репозитория — дать **универсальный каркас** ассистента: typed contracts, оркестрация, инструменты и контроль риска **на уровне кода**, а не только промпта.

---

## 🎯 Кому это нужно

<table>
<tr>
<td width="50%" valign="top">

### ✅ Берите, если вам нужно

- корпоративный ассистент с **контролируемыми** tool-вызовами  
- интеграция с **СЭД / MCP** (например, EDMS)  
- аудитируемый pipeline, а не «чёрный ящик LLM»  
- production-заготовки: Docker, env-профили, retention, observability  

</td>
<td width="50%" valign="top">

### ❌ Не ваш выбор, если

- нужен быстрый одноразовый chatbot без БД  
- не готовы поднять Postgres + Redis + LLM  
- ищете только UI без backend-оркестрации  
- не хотите разбираться с агентами и контрактами  

</td>
</tr>
</table>

---

## 🏗️ Как это работает (30 секунд)

```text
  User text
      │
      ▼
 ┌─────────┐   ┌────────────┐   ┌──────────────┐   ┌────────────┐
 │ Intent  │──▶│ Supervisor │──▶│ ContextWeaver│──▶│ Researcher │─┐
 └─────────┘   └────────────┘   └──────────────┘   └────────────┘ │
                                                                  │
      ┌───────────────────────────────────────────────────────────┘
      ▼
 ┌────────┐     ┌───────────┐     ┌──────────┐
 │ Critic │────▶│ Formatter │────▶│  Answer  │
 └────────┘     └───────────┘     └──────────┘
      ▲
      │  optional MCP tool calls (RBAC + audit)
```

---

## 🚀 Быстрый старт

> Полный путь от `git clone` до API, Docker и эксплуатации — в **[docs/handbook.md](docs/handbook.md)**.

```bash
git clone https://github.com/your-org/palatium-ai.git
cd palatium-ai
poetry install --with dev
cp env/.env.example env/.env   # заполните POSTGRES_*, LLM_*, REDIS_*
poetry run alembic upgrade head
poetry run python -m palatium_ai.main
```

Откройте: **http://127.0.0.1:8000/docs**

| Ссылка | Зачем |
|--------|--------|
| 📖 [Handbook](docs/handbook.md) | Clone → env → Poetry/Docker → API → ops |
| 🐳 [Docker guide](docs/docker.md) | Сборка образа, Compose, troubleshooting |
| 🔐 [Secrets](docs/secrets.md) | Локально / CI / Vault |

---

## 🧭 Стек

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/LangGraph-Orchestration-1B1B1B?style=flat-square" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/MCP-Tools-6E56CF?style=flat-square" alt="MCP"/>
  <img src="https://img.shields.io/badge/LiteLLM-Providers-FF6B35?style=flat-square" alt="LiteLLM"/>
  <img src="https://img.shields.io/badge/PostgreSQL-State-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  <img src="https://img.shields.io/badge/Redis-Cache-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis"/>
  <img src="https://img.shields.io/badge/structlog-Observability-2E8B57?style=flat-square" alt="structlog"/>
  <img src="https://img.shields.io/badge/Docker-Runtime-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker"/>
</p>

---

## 📁 Куда смотреть в коде

```text
src/palatium_ai/
  domain/            # typed contracts
  application/       # agents · LangGraph · services
  infrastructure/    # LLM · MCP · DB · Redis
  presentation/      # FastAPI
env/                 # environment profiles
docs/                # handbook · docker · secrets
```

---

## 📄 License

MIT © Palatium AI contributors — см. [`src/palatium_ai/LICENSE`](src/palatium_ai/LICENSE)

<div align="center">

**Built for teams that treat agents like production software.**

[Get started →](docs/handbook.md)

</div>
