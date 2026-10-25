# Safety Phase 5 — PII scrubber · constitutional critic · nightly red-team

Статус: **S1 DONE (2026-10-24) · S2 DONE (2026-10-24) · S3 DONE (2026-10-24)**.
Родитель: `.cursor/plans/evolution-to-big-tech.md` §8, строка **Phase 5**.
Норматив: 020 (секреты/PII/HITL), 040 (observability), 050/055 (один владелец
решения, без дублей), 010 (типы), 025 (supply chain), 035 (fail-closed), 005 (этот
документ — спека до кода).

Не дублирует правила: здесь только дизайн волн и критерии приёмки.

---

## 0. Разрыв, который закрываем

| # | Разрыв | Где видно |
|---|---|---|
| R1 | PII-паттерны живут **тремя** наборами с разной семантикой | `core/security/secret_scanner.py` (секреты), `core/observability/redaction.py` (логи: email/phone/УНП/IBAN/CC), `domain/memory/pii.py` (память/вложения: email/phone/паспорт) |
| R2 | Один и тот же класс (email, телефон) детектируется дважды, но маска и профиль разные → дрейф молча | email: `[EMAIL]` в памяти vs `<email>` в логах |
| R3 | BY-идентификаторы (УНП, IBAN BY) известны только логам и **не** участвуют в классификации записи | `domain/memory/pii.py` их не видит |
| R4 | Critic проверяет «качество», но не **конституцию** (утечка секрета/PII, следование недоверенной инструкции, обещание необратимого действия) | `application/agents/critic/`, `domain/policies/critic.py` |
| R5 | Red-team прогоняется вручную; ночного гейта нет | `.github/workflows/` — есть `perf-nightly`, `agent-evals-nightly`, red-team нет |

## 1. S1 — единый PII-слой (единственный владелец паттернов)

### Контракты (`core/security/pii/`)

```python
PiiKind = Literal["email", "phone", "iban", "tax_id", "card", "passport"]
PiiProfile = Literal["strict", "observability"]  # strict — запись/классификация
PiiMaskStyle = Literal["bracket", "angle"]  # [EMAIL] vs <email>


class PiiFinding(BaseModel, frozen=True):
    kind: PiiKind
    start: int
    end: int  # НЕ значение: находка безопасна для лога/метрики


class PiiScan(BaseModel, frozen=True):
    findings: tuple[PiiFinding, ...]
    kinds: tuple[PiiKind, ...]  # уникальные, в порядке первого вхождения
```

- `scan_pii(text, *, profile) -> PiiScan`
- `contains_pii(text, *, profile="strict") -> bool`
- `scrub_pii(text, *, profile, style) -> str`

Профиль — не вторая реализация, а **подмножество одного реестра**: каждый детектор
объявляет `profiles: frozenset[PiiProfile]`.

| kind | профили | обоснование |
|---|---|---|
| `email` | strict + observability | было в обоих наборах |
| `phone` | strict + observability | было в обоих |
| `iban` (BY) | strict + observability | классификация теперь видит IBAN (R3) |
| `tax_id` (УНП, 9 цифр) | observability | 9 цифр без контекста слишком шумно для записи |
| `card` (13–19 цифр + Luhn) | strict + observability | Luhn убирает номера заказов |
| `passport` | strict + observability | было в памяти |

### Границы (единственный источник — `core/security/pii`)

| Граница | Профиль | Стиль | Кто делегирует |
|---|---|---|---|
| классификация записи (`contains_pii`, `tag/mask/reject`) | strict | bracket | `domain/memory/pii.py`, `domain/attachments/pii_policy.py` |
| логи/трейсы | observability | angle | `core/observability/redaction.redact` (только PII-часть) |

- Секреты (`sk-`, `AKIA`, `Bearer`, `password=`, PEM) остаются у
  `core/security/secret_scanner.py`; JWT/пути/токены логов — у `redaction`.
  S1 переносит **только PII** и не смешивает два класса в одном реестре.
- Публичные имена `domain/memory/pii.py` (`text_looks_like_pii`, `mask_pii_in_text`,
  `PII_PLACEHOLDER`, `memory_contains_pii`, `mask_memory_value`) сохраняются
  реэкспортом — вызывающий код и тесты не меняются (010: реэкспорт, не дубль).

### Presidio — осознанно отложен (решение 025, а не забытый пункт)

- Пакет `presidio-analyzer` тянет spaCy + модель (~500 MB) в образ; это решение
  supply-chain и runtime-бюджета, а не побочный эффект волны (025, 080).
- Для BY-идентификаторов (УНП, IBAN BY) Presidio всё равно требует собственных
  recognizers — то есть реестр `core/security/pii` остаётся источником истины в любом случае.
- Поэтому S1 закрывает дрейф (R1–R3) без новой зависимости. `PiiScrubberPort`
  вводится, когда появится реальный второй движок; порт «на будущее» без адаптера —
  мёртвый код (050).

### Реализовано в S1 (evidence)

| Пункт | Где |
|---|---|
| реестр классов | `core/security/pii/detectors.py` (`DETECTORS`, `detectors_for`) |
| типы находок | `core/security/pii/models.py` (`PiiFinding` без значения) |
| scan / mask | `core/security/pii/scrub.py` (`scan_pii`, `scrub_pii`, `scrub_from_scan`) |
| запись в память | `domain/memory/pii.py` (`classify_pii`) + `application/services/pii_gate.py` |
| вложения | `domain/attachments/pii_policy.py` (один scan на intake) |
| логи | `core/observability/redaction.py` (PII-часть делегирована) |
| метрика | `palatium_pii_detected_total{kind,profile}` |

### Критерии приёмки S1

1. `rg "recompile\|re\.compile" domain/memory/pii.py core/observability/redaction.py` — PII-паттернов
   в этих файлах нет (только делегирование).
2. Дрейф-тест: email/phone, найденные strict-профилем, находятся и observability-профилем.
3. `[EMAIL]`/`<email>` и прежние маски логов сохранены — существующие тесты зелёные
   (`tests/unit/test_observability_redaction.py`, `test_attachment_extracted_pii.py`,
   `test_wave9_security_fixes.py`).
4. Новое: IBAN и Luhn-карта теперь поднимают `contains_pii` на запись (R3); УНП остаётся
   log-only классом (9 цифр без контекста слишком шумно для классификации записи).
5. Метрика `palatium_pii_detected_total{kind,profile}` (040: реестр метрик, не свои имена).

## 2. S2 — конституционный critic (DONE 2026-10-24)

- `domain/policies/constitution.py`: закрытый `PrincipleId`, `Article`,
  `Constitution.check()` — детерминированные статьи без LLM и без фразовых списков.
- Детерминированно (код, fail-closed):
  `no_secret_echo` (high, по rule-id секрет-сканера), `no_pii_echo_without_permission`
  (medium, сравнивает **значение** спана с текстом входов турна: цитата своего адреса
  легальна, PII «из ниоткуда» — нет).
- Судимо (LLM обязан назвать id): `no_unsafe_action_commitment`,
  `no_untrusted_instruction_following`, `source_attribution_required` — плюс те же
  детерминированные id в общем списке.
- `CriticOutput.violations` — union(судимые, детерминированные), без дублей; любое
  нарушение → `requires_review=true`, `status="partial"`, метрика
  `palatium_constitution_violation_total{principle,source}`.
- Детерминированные проверки идут **до** выбора судьи: passthrough (`format_only`,
  hop-бюджет) не отключает safety-проверку.
- Секрет в контексте уже вырезается Harness'ом; статья остаётся второй линией
  (тест `test_secret_never_reaches_the_critic_through_context` фиксирует слои).
- Промпт собирается из `Constitution.articles()` — текст статьи живёт в одном месте.

## 3. S3 — ночной red-team (DONE 2026-10-24)

- `tests/redteam/corpus.jsonl` — 12 атак + 3 негативных контроля (allow/allow).
- `tests/redteam/test_redteam_corpus.py` (маркер `slow`) — слой-владелец на класс:
  injection → `UntrustedContentPolicy.decide`; PII/секрет → `Constitution.check`;
  tool abuse → `is_tool_invocation_allowed` через `mcp.call` + точный ref.
- `.github/workflows/redteam-nightly.yml` — cron `45 2 * * *`, `workflow_dispatch`,
  Actions по SHA (025), вне PR-пути.
- Детерминизм: ни одного live-LLM вызова, поэтому красный прогон = регрессия гейта.

## 4. Порядок и проверка

| Волна | Зависит от | Гейт |
|---|---|---|
| S1 | — | unit + `ci_quality` |
| S2 | S1 (PII-детекторы для `no_pii_echo`) | unit + agent evals |
| S3 | S2 (конституция = оракул отказа) | nightly + `ci_quality` (маркер `slow` вне PR) |
