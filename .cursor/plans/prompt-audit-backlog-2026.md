# Prompt / controls audit — backlog (2026-11-16)

Спека после закрытия CTCO + liveliness + `reasoning_effort`/`verbosity` wiring.
Приоритет: enforce в CI → конфликт-детекция → role A/B → **uncertainty** →
multi-turn → lean-cut (lean-cut только после baseline §2+§3).

## Закрыто (не трогать без regression)

- Outcome-First / why / few-shot / VerbosityPolicy vs ReasoningEffortPolicy
- `LLMPort` → LiteLLM dials; Anthropic smoke (`output_config.effort`, silent verbosity drop)
- `_VERBOSITY_CAPABLE` + `llm.verbosity.dropped`; AgentConfig / VerbosityPolicy docs
- CI pin: `tests/unit/test_ci_prompt_controls_gates.py` (closures + controls + smoke on PR path)

## Backlog (порядок)

| # | Пункт | Почему | Риск | Owner / срок |
|---|---|---|---|---|
| 1 | **CI closures** | DoD без enforce — локальный | низкий | **DONE 2026-11-16** |
| 2 | **Conflict-linter / LLM-judge** | единственный ⏳ структурного аудита | средний | **@VabGen**, due **2026-12-05** — см. §2 |
| 3 | **Role A/B eval** (Kimi vs OpenAI) | «без role-prefix» без эмпирики | средний | @VabGen после §2 baseline |
| 4 | **Политика неуверенности / clarification** | «любые сценарии»: неполный вход → 4 disposition, не галлюцинация | средний | **DONE** hot-path 2026-11-16; v1.1 A–D soft |
| 5 | **Multi-turn continuity** | смена темы / противоречие prior / «как в прошлый раз» | средний | **IN PROGRESS** fixtures floor=5 + pins (2026-11-16); agent wiring next |
| 6 | **Lean-cut Intent/Formatter** | dense spec = контракт | высокий | **не начинать** до baseline §2+§3 |

## §2 Conflict-linter / LLM-judge

```
TODO(owner=@VabGen, due=2026-12-05, plans/prompt-audit-backlog-2026.md §2):
implement two-layer conflict-linter + non-blocking CI job
```

### Scope

- runtime-промпты из `AUDIT_PROMPT_REVISIONS` — **15** entries (не 13: реестр вырос
  осознанно при CTCO-аудите — option_synthesizer, attachment_map, image_ocr,
  pdf_vision, judge, w9_judge, grounding_judge + agent prompts; pin проверяет `== 15`)
- v1 проверяет **только same-prompt**. Cross-prompt (Intent↔Contextualizer,
  Critic↔Formatter, Researcher↔Formatter) — **после cutover**, с allowlist пар
- **не** проверяет length/CTCO — уже закрыто ручным аудитом и pin-тестами

### Отчётный язык (обязательно)

«0 hard» = **0 hard same-prompt**. Это **не** «всё проверено». Cross-prompt —
после `CUTOVER_DATE` (2026-12-19). CLI печатает это явно.

### Подход (двухслойный)

1. **static heuristic** — regex/структурный, **same-prompt first**:
   - антонимы в **одном `#`-блоке**: `brief|concise` ↔ `detailed|expand`
   - `always` ↔ `never`, `must` ↔ `may` в одном блоке (с noqa на security-fences)
   - cross-prompt — **не в v1**; позже только с allowlist пар и правилом
     «оба агента в одном pipeline на одном входе»
2. **LLM-judge** (sampled, не на каждый PR):
   - prompt: «перечисли пары инструкций, которые несовместимы; объясни почему»
   - вход: один промпт (v1); few-shot на эталонных конфликтах
   - порог: 0 hard conflicts; soft — warning с triage

Почему два слоя: только judge — дорого/нестабильно на PR; только regex — пропустит
семантику. Static = дешёвое очевидное; judge = семантика на sampled-наборе.

### Практические инварианты (v1 / v1.1)

- **5+5 — floor, не ceiling.** Набор растёт с каждым soft-триажем; adversarial
  non-conflicts добавлены (must/may hierarchy, Critic↔shape, IDENTITY↔expand,
  always-untrusted↔never-fence). Ideal recall/fp на маленьком наборе = «не сломано».
- **Escape hatch + ceiling:** `# noqa: conflict-linter — <why>`; `NOQA_MAX=5` в
  `policy.py` + pin. Превышение → ревью или фикс промпта, не «выключить job».
- **Повышение `NOQA_MAX`:** только PR с owner `@VabGen` + запись в этом плане
  (таблица «NOQA_MAX history»: date, old→new, why). Без записи в плане — отклонять.
  Поднятие «потому что надо» без triage exceptions запрещено.
- Pin: `continue-on-error` до/после `CUTOVER_DATE`, непустой manifest, noqa ≤ N,
  registry size == 15.

### Soft triage 2026-11-16 (`must`/`may` — 4 findings)

Все **легитимная иерархия** (must = контракт/security; may = разрешённая гибкость),
не exclusive choice. Heuristic **не различает** hierarchy vs exclusive — известное
ограничение; soft копится только если не триажить. Исходы:

| prompt_id | исход |
|---|---|
| contextualizer.system | легитимно: MUST rewrite/referent vs may phrase pointer |
| critic.system | легитимно: must speak same ids vs may include recalled facts |
| researcher.system | легитимно: MUST full body vs may one-line framing |
| intent_classifier.system | легитимно: must stay false MCP vs may help retrieval |

Зафиксировано в `TRIAGED_SOFT_MUST_MAY`. Фикс v1.1 heuristics (object-scoped must/may)
— optional; не блокер cutover.

### Выход

- CI job `conflict-linter` — **non-blocking** до **2026-12-19**; затем blocking + `--strict`
- отчёт: scope=same_prompt_only; hard/soft; noqa_count
- regression: `tests/fixtures/conflicts/` (floor 5+5, сейчас 5+9)

### DoD §2

- [x] static same-prompt; 0 **hard** same-prompt на registry; fixtures floor+adversarial
- [x] heuristic judge recall ≥ 4/5 (live LLM — later)
- [x] CI job non-blocking + cutover date in workflow + pin (coe / noqa / fixtures / registry)
- [x] soft must/may triage записан (таблица выше)
- [ ] cutover 2026-12-19: `continue-on-error` off + `--strict` + pin flip
- [ ] cross-prompt layer (после cutover)

## §4 Uncertainty (stateless; выше lean-cut) — IN PROGRESS 2026-11-16

**Контракт важнее промпта.** Четыре взаимоисключающих исхода
(`UncertaintyDisposition` в `domain/policies/types.py`):

| disposition | когда |
|---|---|
| `clarification` | названный пробел; default path неверен |
| `default_with_mark` | разумное допущение с пометкой (не silent invent) |
| `honest_refusal` | out of scope / required data absent; также fallback после residual |
| `unknown` | **residual only** — policy не выбрала между тремя выше; **не** user-facing. Downstream: `resolve_for_downstream` → `honest_refusal` (`unknown_fallback:…`) |

Реализация: `UncertaintyPolicy` + `tests/fixtures/uncertainty/` (8 cases, ≥2 на disposition).
Композит `ClarificationGatePolicy` + `GroundingPolicy` — без дубля их правил.

**Disposition — поле контракта** (не лог): `IntentClassifierOutput.uncertainty_disposition`
→ `ContextPacket` → `FormatterInput` / `CriticInput` (`ResolvedUncertaintyDisposition`,
never raw `unknown`). Проводимость: `tests/unit/test_uncertainty_disposition_conductivity.py`.

**Formatter:** `default_with_mark` → `ASSUMPTION_MARK` structural; `mark_exempt_from_verbosity`
— budget `minimal` не режет пометку.

**Critic:** justified `honest_refusal` (reason ∈ out_of_scope / required_data_absent /
Intent-attached `unknown_fallback:*`) → passthrough. Raw planted `unknown` →
`unresolved_unknown_disposition` (invoke) — **не** coerce на гейте (wildcard-лазейка).
Bare refusal без reason → `unjustified_honest_refusal`.

**§4 vs §5:** §4 = stateless signals (в т.ч. `ambiguous_reference_without_prior`
без истории). §5 = multi-turn continuity (смена темы, противоречие prior,
резолв «как в прошлый раз» *с* историей). Отдельные PR; не смешивать.

DoD wiring (2026-11-16): Continuity attach → packet → Formatter/Critic; stream_prefix
до LLM; `continue_on_error_required(as_of=)` + parametrized pin (18/19/20 Dec).

### §4 v1.1 backlog (не блокер cutover 2026-12-19)

| # | Тема | Почему |
|---|---|---|
| A | mark + LLM error after emit | stream rollback невозможен; после mark нужен явный error-frame «предположение не подтвердилось» |
| B | coerce exhausted path UX | `unknown_fallback:exhausted` есть; Formatter/HITL copy после второго stuck unknown |
| C | retrieval_empty re-decide | disposition после empty search |
| D | out_of_scope producer | явный сигнал, не только fixture |

Осталось soft: C + D; A/B — UX после cutover.

**`DocumentMeta.kind` (2026-11-16):** unrelated к §4. Smoke-тест стрима ошибочно
подставил `kind="answer"` (путаница с `continuation_kind`); SoT —
`DocumentKind` Literal (`analysis`/`response`/…, default `analysis`). §4 wiring
`content_document.py` не трогал. §5 не менять `DocumentKind` без ADR.

### NOQA_MAX history

| date | old→new | why | owner |
|---|---|---|---|
| 2026-11-16 | —→5 | initial ceiling (v1.1) | @VabGen |

Повышение — только PR с owner `@VabGen` + новая строка в этой таблице.

## §5 Multi-turn (fixtures first) — floor + v1.1 2026-11-16

**До кода агентов:** hand-authored dialogs + observable signals (не полный текст ответа).

| case_id | сигнал |
|---|---|
| `mt_like_last_time_with_prior` | контраст §4 `like_last_time_without_history`: с prior → answer + trust prior |
| `mt_topic_switch` | new_topic + prior_context_present + **trust_prior=false** |
| `mt_requirement_refine` | pair `(format, shorten)` |
| `mt_correction_accept` | pair `(answer, none)` — `none` намеренно (нет `correct` в TransformationKind; не путать с rewrite) |
| `mt_explicit_reset` | reset continuity trust |
| `mt_reset_then_incomplete` | §4×§5: после reset incomplete → **clarification** (uncertainty survives) |

**Correction → `transformation=none` (закрыто):** refine vs correction = пара
`(continuation_kind, transformation)` — `(format, shorten)` ≠ `(answer, none)`.
По одному `transformation` correction от «не refine» не отделяется; `rewrite`/`amend`
не используются. Проверка — `test_refine_vs_correction_distinct_transformation`.

SoT: `tests/fixtures/multi_turn/dialogs/` + pins `MULTI_TURN_REVISIONS` (sha256).
Harness: `observe()` = ContinuityPolicy + UncertaintyPolicy на frozen stubs.
Floor=5 (suite ≥6 after v1.1). Не трогать `DocumentKind` без ADR.

**§6 lean-cut:** только **после cutover 2026-12-19** (blocking conflict-linter) +
стабильный soft rate / noqa запас / §5 fixtures зелёные. До cutover — §4 v1.1 A/B.

## Вне scope этого плана

- Переписывание промптов «для краткости» без eval baseline (§6)
- Live Anthropic/OpenAI billed smoke в PR (HTTP-stub + opt-in `live_*`)
- Расширение `_VERBOSITY_CAPABLE` без verify на новом провайдере

## DoD аудита (полностью завершён)

1. §1 enforced в CI — **да**
2. §2 conflict detection с owner’ом, сроком и гейтом — **открыто (due 2026-12-05)**
3. §3–§5 — product backlog «живой ассистент»; §6 — только после baseline
