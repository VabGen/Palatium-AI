/**
 * Словари сообщений.
 *
 * Ключи объявлены один раз в русском словаре, английский типизирован как
 * `Record<MessageKey, string>` — поэтому пропущенный перевод = ошибка компиляции,
 * а не русская строка в английском интерфейсе.
 *
 * Локали НЕ грузятся лениво: виджет собирается в single-file IIFE, где
 * динамические импорты запрещены (план 2.4). Оба словаря входят в бандл —
 * это осознанный размен, см. «Статус реализации».
 *
 * Подстановка — `{name}`. Числа форматируются по локали (см. `index.ts`).
 */
export const ru = {
  // --- Шапка ---
  'app.title': 'Palatium',
  'app.tagline': 'Структурированные ответы агентов',
  'header.newChat': 'Новый диалог',
  'header.collapse': 'Свернуть ассистента',
  'badge.dev': 'DEV',
  'badge.ws': 'WS',
  'badge.standalone': 'автономно',

  // --- Лончер ---
  'launcher.label': 'Palatium',
  'launcher.open': 'Открыть ассистента Palatium',

  // --- Пустое состояние ---
  'empty.greeting': 'Здравствуйте, {name}',
  'empty.title': 'Спросите что угодно',
  'empty.body':
    'Ответ придёт структурированным. Его можно скопировать, выгрузить в PDF или оценить.',
  'empty.attachmentsHint':
    'Приложите PDF, DOCX, изображение, CSV, MD или TXT (до {size}) и спросите о нём — файл проверяется до попадания в модель.',
  'empty.suggestion.0': 'Какие планы на сегодня',
  'empty.suggestion.1': 'Составь план встречи на завтра',

  // --- Сообщения ---
  'msg.agentsWorking': 'Агенты работают',
  'msg.emptyResponse': 'Пустой ответ',
  'msg.formatterOutputInvalid':
    'Не удалось оформить ответ как выбор. Попробуйте переформулировать запрос или уточнить варианты.',
  'msg.devGap': 'DEV: документ похож на эксклюзивное меню, но HITL-карточки не созданы.',

  // --- Действия над ответом ---
  'action.like': 'Ответ полезен',
  'action.dislike': 'Ответ не полезен',
  'action.copy': 'Скопировать текст ответа',
  'action.exportPdf': 'Выгрузить в PDF',
  'action.regenerate': 'Сформировать ответ заново',

  // --- Композер ---
  'composer.placeholder': 'Сообщение для Palatium…',
  'composer.attach': 'Прикрепить файл',
  'composer.attachTitle':
    'Прикрепить файл (PDF, DOCX, изображения, CSV, MD, TXT — до {size} каждый)',
  'composer.send': 'Отправить сообщение',
  'composer.counter': '{used} / {limit}',
  'composer.overLimit': ' — слишком длинное сообщение',
  'composer.nearLimit': ' — приближается к лимиту',
  'composer.overLimitTitle': 'Слишком длинное сообщение ({used} / {limit})',
  'composer.removeAttachment': 'Убрать {name}',
  'composer.attachedFiles': 'Прикреплённые файлы',
  'composer.showInField': 'Показать в поле ввода',
  'composer.asDocument': 'как вложение',
  'composer.pastedDefaultPrompt': 'Проанализируй приложенный текст.',
  'composer.pasteTooLarge':
    'Вставка слишком большая для вложения ({size}). Приложите файл вручную.',
  'composer.pasteConverted': 'Длинный текст преобразован во вложение',
  'composer.showInFieldTooLong':
    'Текст длиннее лимита чата ({limit} символов) — оставьте вложением или сократите.',
  'composer.showInFieldUnavailable': 'Текст вложения недоступен для вставки в поле',
  'composer.showInFieldDone': 'Текст возвращён в поле ввода',
  'composer.pasteSlotFull':
    'Нет свободного слота для вложения — удалите файл или отправьте сообщение',

  // --- Уведомления ---
  'toast.tooManyFiles': 'Не более {count} файлов на сообщение',
  'toast.pdfFailed': 'Не удалось выгрузить PDF',
  'toast.resuming': 'Продолжаем после вашего выбора',
  'toast.regenerated': 'Ответ обновлён',
  'toast.regenerateFailed': 'Не удалось обновить ответ',
  'toast.feedbackFailed': 'Не удалось отправить отзыв на сервер',
  'toast.deleteFailed': 'Не удалось удалить файл на сервере — он истечёт по TTL',
  'toast.uploadFailed': 'загрузка не удалась',

  // --- Отказы вложений (см. `lib/attachments.ts`) ---
  'attach.empty': 'файл пустой',
  'attach.tooLarge': 'больше {size}',
  'attach.unsupportedType': 'неподдерживаемый тип файла',
  'attach.typeNotAccepted': 'тип файла не принимается',
  'attach.extensionMismatch': 'расширение не совпадает с типом файла',
  'attach.filenameInvalid': 'имя файла непригодно',
  'attach.turnLimit': 'не более {count} файлов на сообщение',
  'attach.notUploaded': 'загрузка не дошла до хранилища',
  'attach.malware': 'заблокировано: обнаружено вредоносное ПО',
  'attach.scanFailed': 'заблокировано: антивирус недоступен',
  'attach.injection': 'заблокировано: файл содержит инструкции, адресованные ассистенту',
  'attach.parseFailed': 'не удалось прочитать содержимое',
  'attach.activeContent': 'заблокировано: макросы или встроенные объекты Office',
  'attach.imageTooLarge': 'заблокировано: изображение слишком большое для обработки',
  'attach.mimeMismatch': 'содержимое не совпадает с заявленным типом файла',
  'attach.scanning': 'проверка файла…',
  'attach.download': 'Скачать',
  'attach.requestRestore': 'Запросить проверку',
  'attach.restoreRequested': 'Запрос на восстановление отправлен менеджеру',
  'attach.analyze': 'Анализ таблицы',
  'attach.analyzeRequested': 'Запрос на анализ таблицы отправлен',
  'attach.index': 'В базу знаний',
  'attach.indexRequested': 'Индексация отправлена на подтверждение',
  'attach.projectId': 'Проект (база знаний)',
  'attach.projectIdHint': 'Если указан — файл индексируется в project KB',
  'attach.containsPii': 'PII',
  'attach.connectors': 'Внешние источники',
  'attach.connectorReady': 'доступен',
  'attach.connectorUnavailable': 'недоступен',
  'attach.sources': 'Источники',
  'attach.refused': 'файл отклонён',

  // --- HITL-карточки (`components/HitlCards.tsx`, `lib/hitl.ts`) ---
  'hitl.kicker.choice': 'Выберите один вариант',
  'hitl.kicker.tool': 'Подтверждение инструмента',
  'hitl.kicker.review': 'Требуется проверка',
  'hitl.choiceHint': 'Нажмите одну из карточек, чтобы продолжить.',
  'hitl.stepUpHint':
    'Перед выполнением инструмента сервер может потребовать подтверждение личности (step-up).',
  // Label only: the score itself is rendered inline with its risk colour, so it
  // cannot be baked into the translated sentence.
  'hitl.riskLabel': 'Риск',
  'hitl.expires': 'Истекает {time}',
  'hitl.stepUpGroup': 'Подтверждение личности (step-up)',
  'hitl.stepUpVia': 'Step-up через {method}{acr}.',
  'hitl.stepUpBind': 'Привяжите claim {claim}={card}.',
  'hitl.stepUpNonce': ' Одноразовый код: {nonce}.',
  'hitl.stepUpIdpOpened': ' Окно IdP открыто — оно может передать JWT через postMessage.',
  'hitl.stepUpPaste': ' Вставьте JWT от IdP ниже.',
  'hitl.stepUpPlaceholder': 'IdP step-up JWT',
  'hitl.stepUpOpenIdp': 'Открыть IdP',
  'hitl.stepUpSubmit': 'Отправить step-up',
  'hitl.stepUpConfirming': 'Подтверждаем…',
  'hitl.cancel': 'Отмена',
  'hitl.choicesLabel': 'Варианты',
  'hitl.actionsLabel': 'Действия',
  'hitl.saving': 'Сохраняем…',
  'hitl.resolved': 'Выполнено: {action}',
  'hitl.error.stepUpUnavailable': 'Step-up требуется, но сервер не вернул assertion',
  'hitl.error.stepUpRequired': 'Вставьте IdP step-up JWT перед подтверждением.',
  'hitl.error.alreadyAnswered': 'Карточка уже обработана.',
  'hitl.error.expired': 'Срок действия карточки истёк.',
  'hitl.error.forbidden': 'Нет прав на это действие.',

  // --- Действия с памятью (`components/MemoryActions.tsx`) ---
  'memory.toggle': 'Память',
  'memory.panelLabel': 'Действия с памятью (HITL)',
  'memory.modesLabel': 'Действие с памятью',
  'memory.mode.save': 'Сохранить',
  'memory.mode.forget': 'Забыть',
  'memory.mode.extract': 'Извлечь',
  'memory.entryKeyPlaceholder': 'entry_key (например, pref-lang)',
  'memory.textPlaceholder': 'Что запомнить?',
  'memory.extractHint':
    'Поставить в очередь sleep-time extract для диалога (transcript → medium, требует подтверждения). Не переносит факты в граф знаний.',
  'memory.submit.save': 'Запросить сохранение',
  'memory.submit.forget': 'Запросить забывание',
  'memory.submit.extract': 'Запросить извлечение',
  'memory.label.save': 'Сохранение в память ожидает подтверждения',
  'memory.label.forget': 'Забывание из памяти ожидает подтверждения',
  'memory.label.extract': 'Извлечение из диалога ожидает подтверждения',
  'memory.error.entryKey': 'Укажите entry_key',
  'memory.error.entryKeyAndText': 'Укажите entry_key и текст',
  'memory.error.requestFailed': 'Запрос к памяти не выполнен',
  'memory.toast.cardCreated': 'HITL-карточка создана',

  // --- Ошибки клиента ---
  'error.emptyMessage': 'Сообщение не может быть пустым.',
  'error.messageTooLong':
    'Сообщение слишком длинное: {used} / {limit} символов. Для больших текстов приложите файл или отправьте через раздел «Документы».',
  'error.tooManyAttachments': 'Не более {count} вложений на одно сообщение.',
  'error.noToken': 'Нет access-токена: автономный режим требует идентификатор пользователя',
  'error.devTokenDisabled': 'Выпуск dev-токена отключён в режиме host',
  'error.hostRefreshTimeout': 'Host не обновил токен вовремя',
  'error.requestFailed': 'Запрос не выполнен',
  'error.invalidContext': 'setContext() требует корректный SedContext',
  'error.tenantMismatch':
    'Контекст СЭД противоречив: tenant в токене, user.orgId и scope.tenantId не совпадают. Виджет работает автономно — хосту нужно прислать согласованный контекст.',
} as const;

export type MessageKey = keyof typeof ru;

export const en: Record<MessageKey, string> = {
  'app.title': 'Palatium',
  'app.tagline': 'Structured agent replies',
  'header.newChat': 'New chat',
  'header.collapse': 'Collapse assistant',
  'badge.dev': 'DEV',
  'badge.ws': 'WS',
  'badge.standalone': 'standalone',

  'launcher.label': 'Palatium',
  'launcher.open': 'Open the Palatium assistant',

  'empty.greeting': 'Hello, {name}',
  'empty.title': 'Ask anything',
  'empty.body': "I'll provide structured answers. You can copy, export, or give feedback.",
  'empty.attachmentsHint':
    'Attach a PDF, DOCX, image, CSV, MD or TXT (up to {size}) and ask about it — the file is scanned before it reaches a model.',
  'empty.suggestion.0': "What is on today's agenda",
  'empty.suggestion.1': "Draft an agenda for tomorrow's meeting",

  'msg.agentsWorking': 'Agents working',
  'msg.emptyResponse': 'Empty response',
  'msg.formatterOutputInvalid':
    'Could not present this answer as a choice. Try rephrasing or listing the options you need.',
  'msg.devGap': 'DEV: document looks like an exclusive menu but no HITL cards were minted.',

  'action.like': 'Like this response',
  'action.dislike': 'Dislike this response',
  'action.copy': 'Copy response text',
  'action.exportPdf': 'Export as PDF',
  'action.regenerate': 'Regenerate response',

  'composer.placeholder': 'Message Palatium…',
  'composer.attach': 'Attach a file',
  'composer.attachTitle': 'Attach a file (PDF, DOCX, images, CSV, MD, TXT — up to {size} each)',
  'composer.send': 'Send message',
  'composer.counter': '{used} / {limit}',
  'composer.overLimit': ' — too long',
  'composer.nearLimit': ' — approaching the limit',
  'composer.overLimitTitle': 'Message is too long ({used} / {limit})',
  'composer.removeAttachment': 'Remove {name}',
  'composer.attachedFiles': 'Attached files',
  'composer.showInField': 'Show in text field',
  'composer.asDocument': 'as attachment',
  'composer.pastedDefaultPrompt': 'Analyze the attached text.',
  'composer.pasteTooLarge': 'Paste is too large for an attachment ({size}). Attach a file instead.',
  'composer.pasteConverted': 'Long paste converted to an attachment',
  'composer.showInFieldTooLong':
    'Text exceeds the chat limit ({limit} characters) — keep it as an attachment or shorten it.',
  'composer.showInFieldUnavailable': 'Attachment text is not available to restore into the field',
  'composer.showInFieldDone': 'Text restored to the input field',
  'composer.pasteSlotFull': 'No attachment slot left — remove a file or send the message',

  'toast.tooManyFiles': 'No more than {count} files per message',
  'toast.pdfFailed': 'PDF export failed',
  'toast.resuming': 'Continuing after your choice',
  'toast.regenerated': 'Answer updated',
  'toast.regenerateFailed': 'Could not update the answer',
  'toast.feedbackFailed': 'Feedback was not sent to the server',
  'toast.deleteFailed': 'Could not delete the file on the server — it will expire by TTL',
  'toast.uploadFailed': 'upload failed',

  'attach.empty': 'file is empty',
  'attach.tooLarge': 'larger than {size}',
  'attach.unsupportedType': 'unsupported file type',
  'attach.typeNotAccepted': 'file type is not accepted',
  'attach.extensionMismatch': 'extension does not match the file type',
  'attach.filenameInvalid': 'file name is not usable',
  'attach.turnLimit': 'no more than {count} files per message',
  'attach.notUploaded': 'upload did not reach storage',
  'attach.malware': 'blocked: malware detected',
  'attach.scanFailed': 'blocked: antivirus unavailable',
  'attach.injection': 'blocked: the file contains instructions aimed at the assistant',
  'attach.parseFailed': 'contents could not be read',
  'attach.activeContent': 'blocked: Office macros or embedded objects',
  'attach.imageTooLarge': 'blocked: image is too large to process',
  'attach.mimeMismatch': 'contents do not match the declared file type',
  'attach.scanning': 'scanning file…',
  'attach.download': 'Download',
  'attach.requestRestore': 'Request review',
  'attach.restoreRequested': 'Restore request sent to a manager',
  'attach.analyze': 'Analyze table',
  'attach.analyzeRequested': 'Table analysis request sent',
  'attach.index': 'Add to knowledge',
  'attach.indexRequested': 'Indexing sent for approval',
  'attach.projectId': 'Project (knowledge base)',
  'attach.projectIdHint': 'When set, the file is indexed into that project KB',
  'attach.containsPii': 'PII',
  'attach.connectors': 'External sources',
  'attach.connectorReady': 'ready',
  'attach.connectorUnavailable': 'unavailable',
  'attach.sources': 'Sources',
  'attach.refused': 'file was refused',

  'hitl.kicker.choice': 'Choose one',
  'hitl.kicker.tool': 'Tool approval',
  'hitl.kicker.review': 'Review required',
  'hitl.choiceHint': 'Click one option card to continue.',
  'hitl.stepUpHint':
    'Tool approval may require a server-issued step-up proof before the action runs.',
  'hitl.riskLabel': 'Risk',
  'hitl.expires': 'Expires {time}',
  'hitl.stepUpGroup': 'IdP step-up assertion',
  'hitl.stepUpVia': 'Step-up via {method}{acr}.',
  'hitl.stepUpBind': 'Bind claim {claim}={card}.',
  'hitl.stepUpNonce': ' Challenge nonce: {nonce}.',
  'hitl.stepUpIdpOpened': ' IdP window opened — it may postMessage the JWT.',
  'hitl.stepUpPaste': ' Paste the IdP JWT below.',
  'hitl.stepUpPlaceholder': 'IdP step-up JWT',
  'hitl.stepUpOpenIdp': 'Open IdP',
  'hitl.stepUpSubmit': 'Submit step-up',
  'hitl.stepUpConfirming': 'Confirming…',
  'hitl.cancel': 'Cancel',
  'hitl.choicesLabel': 'Choices',
  'hitl.actionsLabel': 'HITL actions',
  'hitl.saving': 'Saving…',
  'hitl.resolved': 'Resolved: {action}',
  'hitl.error.stepUpUnavailable': 'Step-up required but the server returned no assertion',
  'hitl.error.stepUpRequired':
    'Provide the IdP step-up JWT (paste or IdP postMessage) before confirming.',
  'hitl.error.alreadyAnswered': 'This card was already answered.',
  'hitl.error.expired': 'This card has expired.',
  'hitl.error.forbidden': 'You are not allowed to act on this card.',

  'memory.toggle': 'Memory',
  'memory.panelLabel': 'Memory HITL actions',
  'memory.modesLabel': 'Memory action',
  'memory.mode.save': 'Save',
  'memory.mode.forget': 'Forget',
  'memory.mode.extract': 'Extract',
  'memory.entryKeyPlaceholder': 'entry_key (e.g. pref-lang)',
  'memory.textPlaceholder': 'What should be remembered?',
  'memory.extractHint':
    'Queue sleep-time extract for this thread (transcript → medium; requires approve). Does not promote facts into the knowledge graph.',
  'memory.submit.save': 'Request save',
  'memory.submit.forget': 'Request forget',
  'memory.submit.extract': 'Request extract',
  'memory.label.save': 'Memory save awaiting approval',
  'memory.label.forget': 'Memory forget awaiting approval',
  'memory.label.extract': 'Memory extract awaiting approval',
  'memory.error.entryKey': 'Entry key is required',
  'memory.error.entryKeyAndText': 'Entry key and text are required',
  'memory.error.requestFailed': 'Memory request failed',
  'memory.toast.cardCreated': 'HITL card created',

  'error.emptyMessage': 'Message cannot be empty.',
  'error.messageTooLong':
    'Message is too long: {used} / {limit} characters. For large texts, attach a file or send it via the Documents section.',
  'error.tooManyAttachments': 'No more than {count} attachments per message.',
  'error.noToken': 'No access token available: standalone mode requires a user id',
  'error.devTokenDisabled': 'Dev token minting is disabled in host mode',
  'error.hostRefreshTimeout': 'Host did not refresh the token in time',
  'error.requestFailed': 'Request failed',
  'error.invalidContext': 'setContext() requires a valid SedContext',
  'error.tenantMismatch':
    'The EDMS context is inconsistent: the token tenant, user.orgId and scope.tenantId do not match. The widget runs standalone — the host must send a consistent context.',
};
