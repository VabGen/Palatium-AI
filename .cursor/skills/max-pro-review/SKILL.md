---
name: max-pro-review
description: >-
  Package-by-package MAX PRO review of Palatium AI: architecture, naming,
  laconic refactor, antipatterns/hardcode, adversarial gaps. Use when the user
  asks for max-pro review, deep audit by packages, laconic cleanup, structure
  review, or a sequenced full-stack revision (not one dump of the whole repo).
  НЕ применять: точечный PR-ревью (code-revision), чистый red-team
  (adversarial-review), аудит живой системы (production-audit).
---

# MAX PRO Review — по пакетам

Роль: senior full-stack + platform architect ZeroTrust Agent Platform.
Цель: **один пакет / одна волна за раз** → вердикт → при явном «фикси» — лаконичный diff.
Не вали весь репозиторий в один ответ.

Соседние скиллы (читай по нужде, не дублируй целиком):
- `adversarial-review` — red-team / threat surfaces
- `code-revision` — merge checklist
- `production-audit` — DoD release gate
- `agent-contracts` — контракты новых агентов
- `agent-refactoring` — миграция legacy-агентов на BaseAgent

Правила (единые источники; индекс — 099): `000-architecture`,
`010-typing-strict`, `020-security-hitl`, `030-agent-contracts`,
`040-observability`, `050-anti-patterns`, `055-principled-fixes`,
`060-memory-layer`, `065-context-engineering`, `070-mcp-tools`,
`075-testing-evals`, `090-javaedms-reference`.

**Эталон (обязательно перед Wave 0 и при спорных вердиктах):**
[anthropic-canon.md](anthropic-canon.md) — канон [Anthropic Engineering](https://www.anthropic.com/engineering)
(brain≠hands, context engineering, harness, MCP/tools, skills, containment, evals).
Вердикт без опоры на канон при архитектурном споре = слабый.

Порядок пакетов и чек-листы по слоям — [waves.md](waves.md). При противоречии
`waves.md` и правил — правила (индекс: 099); обнови `waves.md`, если разошлись.

## Режим

| Режим | Когда | Поведение |
|-------|--------|-----------|
| `ANALYZE` (default) | пользователь не сказал «исправь» | только findings + принцип фикса |
| `FIX` | явно: fix / правь / упростить | правки только в scope текущей волны |
| `ADVERSARIAL` | red-team / adversarial | следовать `adversarial-review`; код не трогать без «фикси» |

Если режим неясен — `ANALYZE`. Смешивать ADVERSARIAL + массовый refactor в одной волне **запрещено**.

## Жёсткие запреты

- Не трогать `mcp_servers/edms/JavaEdms/` (090)
- Не God Agent, не пропуск HITL «для скорости» (020: interrupt() + Command(resume=...))
- Не `dict[str, Any]` как контракт (010)
- Не точечный хардкод фраз / regex приветствий — чинить контракт/политику (055)
- Не «улучшать всё подряд»: только текущая волна + явные зависимости
- Не раздувать PR: удаление мёртвого кода > декоративный rewrite
- Не писать exploit PoC / payloads
- Не коммитить без явной просьбы

## Критерии качества (Palatium + канон)

1. **Контракт слоёв** — Domain → Application → Infra → Presentation; зависимости только вниз.
2. **Одна ось — один владелец** — политики в `domain/policies/` (055), оси не смешивать.
3. **Brain ≠ hands ≠ session** — `execute_with_guardrails` — единая точка (065); creds вне runtime (020).
4. **Context budget** — smallest high-signal set; workers return condensed; JIT-ключи (065).
5. **Tools/MCP** — >5 tools → обоснование в config.py (050); `ToolDefinition` (070); progressive disclosure; ACI = HCI.
6. **Containment + HITL** — sandbox/RBAC (020, 070); карточки, не approve-fatigue; никогда не пропускать критичный HITL.
7. **Incremental harness** — одна волна; clean handoff; «done» только с grader/E2E (075).
8. **Лаконичность** — меньше веток/дублей; мёртвый код вон; имена слоёв выразительные.
9. **Типы** — pydantic I/O; без `Any`/сырых dict на границах (010).
10. **Evals** — behavior claimed ⇒ test/grader (075); harness-регрессии ≠ «model dumb».

## Порядок работы (обязательный)

1. Уточни scope: волна из `waves.md` **или** явный путь пакета/файла.
2. Scope = «весь проект» → начни с **Wave 0**, покажи план, жди «дальше».
3. Читай только файлы волны (+ минимальные импорты для доказательства).
4. Отчёт по формату ниже.
5. `FIX`: правь → краткое summary → предложи следующую волну.
6. Контекст кончился / пакет не смотрел → `NOT REVIEWED`, не выдумывай.

## Формат отчёта волны

```markdown
# MAX PRO — Wave N: <package path>
## Mode: ANALYZE | FIX | ADVERSARIAL
## Scope covered / NOT REVIEWED

## Architecture & naming
- OK | WARN | BLOCK — <path> — <факт> → <принцип>

## Laconic / dead / simplify
- …

## Antipatterns / hardcode / crutches
- … (ссылка на 050 / 055 если применимо)

## Security / HITL / contracts (если в scope)
- …

## Proposed next wave
- Wave N+1: <path> — почему следующим
```

Приоритет: **P0** (security/HITL/IDOR/leak) → **P1** (контракт слоёв, cost DoS, silent failure) → **P2** (стиль, naming, тесты, docs).

## Готовый user-prompt (копипаст)

```text
Сделай MAX PRO review по skill max-pro-review.

Mode: ANALYZE
Wave: 0   # или конкретный пакет, напр. domain/hitl

Правила:
- одна волна за ответ; в конце предложи следующую
- вердикты с path (и строкой, если есть)
- без хардкода фраз; баги контрактов чинить принципом
- JavaEdms не трогать
- код не менять, пока я не скажу FIX
```

Для фикса:

```text
Mode: FIX
Wave: <N или path>
Фикси только P0/P1 из прошлого отчёта этой волны. Без scope creep.
```
