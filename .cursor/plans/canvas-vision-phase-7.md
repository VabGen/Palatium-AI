# Canvas / Vision — Phase 7

Статус: **S0 DONE (2026-10-25) · S1 CLOSED BY DECISION (ADR 0006) · S2a DONE
(2026-10-25) · S2b DONE (2026-10-25, алиас `vision-tier`, fallback off) · S3 NEXT
(vision-eval; нужен живой gateway)**.
Родитель: `.cursor/plans/evolution-to-big-tech.md` §8, строка **Phase 7**.
Норматив: 005 (этот файл — спека до кода), 086, 010, 020/040, 075, 050/055
(один владелец решения, без дублей). Решения — ADR
[0006](../../docs/adr/0006-canvas-server-authoritative-documents.md) и
[0007](../../docs/adr/0007-vision-image-parts.md).

---

## 0. Разрыв

| # | Разрыв | Где видно |
|---|---|---|
| R1 | Роадмап обещает Yjs CRDT, но сценария совместного редактирования нет: тред — один владелец, доставка односторонняя (SSE), правка — reject → новый turn | `.cursor/plans/evolution-to-big-tech.md` §8; `docs/architecture/streaming.md` |
| R2 | Изображение доходит до модели только как OCR-текст — визуальная семантика теряется | `domain/llm/models.py` (`ChatMessage.content: str`), `infrastructure/parsing/document_parser.py` |
| R3 | Нет решения, чем платить за vision-токены и какая модель разрешена | `core/types/model_registry.py` — только текстовые tier'ы |
| R4 | Vision-кейсов нет в evals: «картинка → описание» не проверяется | `application/agents/*/evals/` |

## 1. Scope

- ADR 0006: Canvas = server-authoritative `ContentDocument`, Yjs отклонён.
- ADR 0007: vision как аддитивная часть сообщения (`ImagePart`), OCR остаётся.
- Этот план (границы, волны, DoD, открытые вопросы).

## 2. Вне scope

- Клиентский канал доставки `image_parts` до агента (меняет контракт 030 — отдельная
  волна; сервис и адаптер готовы).
- Yjs/CRDT, offline editing, presence/awareness.
- Экспорт артефактов (Markdown/DOCX/PDF) — отдельная задача, если появится требование.
- Новые блоки `ContentDocument` — только по ADR 0005 §решение 6.
- Любые правки OCR-пайплайна и attachment-контрактов.

## 3. Волны

### S0 — решения (done, 2026-10-25)

- ADR 0006 `accepted`; ADR 0007 `proposed` с блокером.
- Реестры ADR (`docs/adr/README.md`) и `docs/README.md` обновлены.
- Строка Phase 7 в роадмапе отражает фактический статус, а не черновик.

### S1 — Canvas закрыт решением, без кода (closed by decision)

Проверено, что артефактные примитивы уже есть и покрывают потребность:

| Потребность Canvas | Где уже реализовано |
|---|---|
| Таблицы, графики, шаги, ключ-значение | `TableBlock`, `ChartBlock`, `StepsBlock`, `KeyValueBlock` |
| Внешний артефакт (дашборд, доска) | `WidgetBlock` (opaque `kind`/`ref_id`, absolute http(s)) |
| Интерактив/выбор | `ActionSpec`, HITL-карточки (`020`) |
| История и подсветка правок | `DocumentRevision` + `RevisionNote` (`domain/content/revision.py`) |

Кода нет намеренно: добавлять CRDT-движок ради несуществующего сценария — цена без
потребителя (050). Повторное открытие вопроса — только новым ADR.

### S2a — vision contract + admission policy (DONE, 2026-10-25)

- `domain/llm/models.py`: `ImagePart` (`attachment_id` + `mime` из закрытого
  `VISION_IMAGE_MIMES`), `ChatMessage.image_parts` (аддитивно), валидатор «только `user`».
- `domain/llm/errors.py`: `VisionUnsupportedError` — capability gap, не outage.
- `domain/policies/vision.py`: `VisionPolicy.decide` — mime → размер → PII → алиас;
  PII блокируется безусловно (флага разрешения нет — это решение владельца, не конфиг).
- `infrastructure/llm/litellm_adapter.py`: при `image_parts` — явный отказ, а не тихий
  drop текстовой половины.
- `infrastructure/llm/factory.py`: отказ по vision в цепочке не открывает breaker и
  сообщается как `VisionUnsupportedError`, а не как падение провайдера.
- Тесты: `tests/unit/test_vision_contract.py`.

### S2b — vision route (DONE, 2026-10-25)
Решение владельца: алиас `vision-tier`, fallback выключен (vision → text-модель
искажает результат, а не деградирует). Реализовано:

1. `core/config/llm`: `LLM_VISION_MODEL` (пусто → маршрут выключен, fail-closed),
   `LLM_VISION_MAX_IMAGE_BYTES` (10 MiB), `LLM_VISION_MAX_IMAGES` (4); те же ключи в
   `env/.env.example` и деплой-примерах.
2. `domain/ports/vision.py` (`VisionImageSourcePort`) + `infrastructure/vision/blob_image_source.py`:
   `attachment_id` → `AttachmentIntakePolicy.blob_key` → `stat` (размер/MIME из хранилища) →
   `read_bytes` → decode guard. Несовпадение MIME, отсутствие объекта и превышение потолка —
   `VisionImageUnavailableError`.
3. `application/services/vision_images.py` (`VisionImageService`): строки вложений одного
   владельца → `VisionPolicy` **до** чтения байтов (`contains_pii` из строки) → `ImagePart`s
   или `denials` с типизированной причиной; каждая картинка считается в
   `palatium_vision_image_total{outcome,reason}`.
4. `LiteLLMAdapter`: `image_url` c data URL из blob, модель — `LLM_VISION_MODEL`
   (tier агента игнорируется при наличии частей); без алиаса/источника — `VisionUnsupportedError`.
5. `LLMClientFactory` / `_FallbackChainLLMAdapter`: вызов с `image_parts` идёт только в
   primary — ни fallback, ни открытия breaker по capability-отказу.
6. Composition root: `BlobVisionImageSource` + `VisionImageService` собираются в bootstrap
   (только при наличии attachment-портов), `AppResources.vision_images`.
7. Тесты: `tests/unit/test_vision_contract.py` (контракт/политика/no-fallback) и
   `tests/unit/test_vision_route.py` (blob-резолв, `image_url`, лимиты из storage,
   PII/количество/чужой владелец, vision-алиас вместо текстовой модели).

DoD S2b (частично проверяемо здесь): контракт → `image_url`, лимиты/MIME из хранилища,
отказ без алиаса, PII-блок, отсутствие base64 в логах — покрыто unit-тестами.
Сквозной сценарий «картинка с графиком → модель описывает график» требует живого gateway
и относится к S3.

Осталось вне S2b (отдельная волна, меняет контракт 030): канал доставки `image_parts`
от API-запроса до агента — `AgentInput` по-прежнему `dict[str, str]`, поэтому агенты
пока не формируют image-сообщения; сервис и адаптер к этому готовы.

### S3 — vision eval (NEXT; нужен живой gateway)

- Кейсы в `application/agents/<agent>/evals/`: график, схема, таблица-картинка,
  нечитаемое изображение (ожидается честный отказ), PII на изображении (ожидается
  маскирование/отказ).
- Прогон — через существующий prompt/eval gate (Phase 6), без нового гейта.

## 4. DoD (S0 + S1 + S2a + S2b)

- ADR 0006 и ADR 0007 — `accepted`; vision-маршрут реализован и покрыт тестами.
- Реестры ADR и `docs/README.md` ссылаются на оба ADR (086).
- Роадмап: Canvas помечен closed by decision, vision — S2b done, S3 next.
- Контракт `ImagePart` + `VisionPolicy` + fail-closed отказ адаптера + blob-резолв +
  no-fallback покрыты тестами (`test_vision_contract.py`, `test_vision_route.py`).
- Открытые вопросы §6: алиас закрыт; PII-вопрос остаётся решением владельца.

## 5. Enforcement / гейт

- Автоматического гейта «Yjs не появился» **нет** — врать про автоматизацию нельзя (005).
  Гейт — ревью: новая CRDT-зависимость (`yjs`, `y-websocket`, `y-prosemirror`) или второй
  движок документа = блок до нового ADR.
- Vision: `tests/unit/test_vision_contract.py` и `tests/unit/test_vision_route.py` падают,
  если `image_parts` начнут молча отбрасываться, если PII-изображение пройдёт политику,
  если vision-отказ откроет breaker провайдера, если image-вызов уйдёт на текстовую
  модель/в fallback или если лимиты возьмутся из клиентского заявления, а не из storage.

## 6. Открытые вопросы

1. **Алиас vision-модели** — закрыт 2026-10-25: `vision-tier` на gateway, fallback
   выключен (vision → text-модель искажает результат). См. ADR 0007 §Конфигурация.
2. **PII:** разрешён ли PII-класс изображений на этом gateway (документы, персональные
   данные)? Пока ответа нет — `pii_blocked` безусловен, остальное идёт по OCR + HITL.

Закрытие вопросов фиксируется здесь строкой «закрыт: <решение, дата>» со ссылкой на
ADR/конфиг; история не переписывается (005).
