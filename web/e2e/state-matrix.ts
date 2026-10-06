/**
 * Матрица состояний виджета (W8) — явный артефакт вместо Storybook.
 *
 * Один источник истины: каждый кадр объявляет, ЧТО его вызывает (мок-ответы и
 * действия пользователя) и ЧТО он обязан показать (проверки). `state-matrix.spec.ts`
 * исполняет матрицу, `docs/embedded-assistant.md` §7 ссылается на неё как на
 * перечень состояний. Проза без исполнения дрейфует — здесь её нет.
 *
 * Полезные нагрузки берутся из `fixtures.ts`, а не пишутся здесь заново: форма
 * ответа описана в одном месте, поэтому изменение контракта правится один раз.
 *
 * Кадры покрывают обе оси, которые ломаются незаметно:
 *  - состояния, приходящие С СЕРВЕРА (pending/answer/error/HITL/memory/вложения);
 *  - состояния, задаваемые ХОСТОМ (`collapsed`, light theme).
 *
 * Проверки декларативны намеренно: их интерпретирует тест (`runCheck`), поэтому
 * матрицу можно читать как таблицу требований, не проваливаясь в код.
 */
import type { Page } from '@playwright/test';
import type { DialogTurnResponse } from '../src/types/contentDocument';
import type { Reply } from './mock-server';
import {
  E2E_PDF_BYTES,
  answerDocument,
  attachmentTicket,
  choiceCard,
  dialogTurn,
  formatterResult,
  quarantinedAttachment,
  readyAttachment,
  resolvedCard,
  stepUpChallenge,
  toolCard,
  uploadedAttachment,
} from './fixtures';

/** Что проверить в кадре. Пустой селектор означает сам элемент `<palatium-assistant>`. */
export type Check =
  /** Текст элемента содержит подстроку. */
  | { kind: 'text'; selector: string; contains: string }
  | { kind: 'visible'; selector: string }
  | { kind: 'hidden'; selector: string }
  | { kind: 'count'; selector: string; count: number }
  /** Атрибут присутствует; `value` — если нужно точное значение. */
  | { kind: 'attr'; selector: string; name: string; value?: string }
  | { kind: 'disabled'; selector: string }
  /** CSS-переменная на элементе — так проверяется темизация и токены. */
  | { kind: 'cssVar'; selector: string; name: string; value: string }
  /** Ни одна видимая строка не осталась английской при `lang="ru"`. */
  | { kind: 'noEnglish' };

export type ApiScript = { key: string; replies: readonly Reply[] };

export type WidgetState = {
  /** Стабильный id кадра: идёт в имя теста и в таблицу состояний. */
  id: string;
  /** Заголовок по-человечески (для отчёта и документации). */
  title: string;
  /** Какое требование доказывает кадр — в одном предложении. */
  proves: string;
  /** Ответы API: ключи эндпоинтов из `mock-server.ts`. */
  api: readonly ApiScript[];
  /** История диалога для ветки hydrate; `undefined` — пустая. */
  turns?: readonly DialogTurnResponse[];
  /** Действия пользователя после загрузки (ввод, клики, файлы). */
  drive?: (page: Page) => Promise<void>;
  checks: readonly Check[];
};

/** Ответ есть, но приходит с задержкой — окно, в котором виден `pending`. */
const SLOW_MS = 1_500;

async function pickPdf(page: Page, name: string): Promise<void> {
  await page.locator('input[type=file]').setInputFiles({
    name,
    mimeType: 'application/pdf',
    buffer: E2E_PDF_BYTES,
  });
}

async function ask(page: Page, text: string): Promise<void> {
  await page.getByRole('textbox').fill(text);
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
}

export const STATE_MATRIX: readonly WidgetState[] = [
  {
    id: 'empty',
    title: 'Пустой диалог',
    proves: 'Виджет стартует автономно, показывает подсказки и не даёт отправить пустоту.',
    api: [],
    checks: [
      { kind: 'count', selector: '.msg', count: 0 },
      { kind: 'text', selector: '.empty h2', contains: 'Спросите что угодно' },
      { kind: 'count', selector: '.suggestion', count: 2 },
      { kind: 'disabled', selector: '.send-btn' },
      { kind: 'text', selector: '.dev-badge:has-text("автономно")', contains: 'автономно' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'history',
    title: 'Восстановленная история',
    proves: 'Диалог с сервера разворачивается в транскрипт, а не теряется при перезагрузке.',
    api: [],
    turns: [
      dialogTurn('user', 'Какие планы на сегодня', 1),
      dialogTurn('assistant', 'Три встречи', 2),
    ],
    checks: [
      { kind: 'count', selector: '.msg', count: 2 },
      { kind: 'text', selector: '.msg.user .bubble', contains: 'Какие планы на сегодня' },
      { kind: 'visible', selector: '.msg.assistant .block-paragraph' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'pending',
    title: 'Запрос в работе',
    proves: 'Пока агенты работают, пользователь видит индикатор, а отправка заблокирована.',
    api: [
      {
        key: 'intents.process',
        replies: [{ delayMs: SLOW_MS, json: formatterResult({ output: answerDocument() }) }],
      },
    ],
    drive: async page => ask(page, 'Составь письмо'),
    checks: [
      { kind: 'visible', selector: '.typing-dots' },
      { kind: 'text', selector: '.msg.pending', contains: 'Агенты работают' },
      { kind: 'disabled', selector: '.send-btn' },
      { kind: 'text', selector: '.msg.user .bubble', contains: 'Составь письмо' },
    ],
  },
  {
    id: 'answer',
    title: 'Ответ агента',
    proves: 'Структурированный ответ рендерится блоками и получает полный набор действий.',
    api: [{ key: 'intents.process', replies: [{ json: formatterResult() }] }],
    drive: async page => ask(page, 'Составь письмо'),
    checks: [
      { kind: 'visible', selector: '.msg.assistant .block-paragraph' },
      { kind: 'visible', selector: '.msg.assistant .kv-row' },
      { kind: 'attr', selector: '.msg-actions button', name: 'aria-label', value: 'Ответ полезен' },
      { kind: 'hidden', selector: '.typing-dots' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'error.server',
    title: 'Ошибка сервера',
    proves: '5xx не глотается: пользователь видит причину, а не пустой ответ.',
    api: [
      {
        key: 'intents.process',
        replies: [{ status: 503, json: { detail: 'LiteLLM недоступен' } }],
      },
    ],
    drive: async page => ask(page, 'Составь письмо'),
    checks: [
      { kind: 'text', selector: '.msg-error', contains: 'LiteLLM недоступен' },
      { kind: 'count', selector: '.msg-actions', count: 0 },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'hitl.choice',
    title: 'HITL: выбор варианта',
    proves: 'Карточка выбора — кликабельные карточки с ролью group, а не текстовый список.',
    api: [
      {
        key: 'intents.process',
        replies: [{ json: formatterResult({ output: null, hitl_cards: [choiceCard()] }) }],
      },
    ],
    drive: async page => ask(page, 'Какой тон письма?'),
    checks: [
      { kind: 'visible', selector: '.hitl-card' },
      { kind: 'text', selector: '.hitl-kicker', contains: 'Выберите один вариант' },
      { kind: 'count', selector: '.hitl-options button', count: 2 },
      { kind: 'attr', selector: '.hitl-options', name: 'aria-label', value: 'Варианты' },
      { kind: 'visible', selector: '.hitl-choice-hint' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'hitl.step-up',
    title: 'HITL: инструмент через step-up',
    proves:
      'Необратимое действие требует step-up: карточка не отправляет запрос без подтверждения.',
    api: [
      {
        key: 'intents.process',
        replies: [
          {
            json: formatterResult({
              output: answerDocument('Черновик готов к отправке.'),
              hitl_cards: [toolCard()],
            }),
          },
        ],
      },
      { key: 'hitl.step-up', replies: [{ json: stepUpChallenge() }] },
      {
        key: 'hitl.respond',
        replies: [
          {
            json: {
              resolve: { card: resolvedCard('formal'), replayed: false, message: 'ok' },
            },
          },
        ],
      },
    ],
    drive: async page => {
      await ask(page, 'Отправь письмо');
      await page.getByRole('button', { name: 'Отправить', exact: true }).click();
      await page.locator('.hitl-step-up-input').fill('idp.jwt.assertion');
      await page.getByRole('button', { name: 'Отправить step-up' }).click();
    },
    checks: [
      // После резолва карточка уходит из транскрипта, а документ остаётся видимым.
      { kind: 'hidden', selector: '.hitl-card' },
      { kind: 'hidden', selector: '.hitl-step-up-form' },
      { kind: 'visible', selector: '.msg.assistant .block-paragraph' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'hitl.respond-error',
    title: 'HITL: карточка просрочена',
    proves: '410 от карточки переводится в понятный текст, а не показывается как HTTP-код.',
    api: [
      {
        key: 'intents.process',
        replies: [{ json: formatterResult({ output: null, hitl_cards: [choiceCard()] }) }],
      },
      { key: 'hitl.respond', replies: [{ status: 410, json: { detail: 'card expired' } }] },
    ],
    drive: async page => {
      await ask(page, 'Какой тон?');
      await page.getByRole('button', { name: 'Официальный' }).click();
    },
    checks: [
      { kind: 'text', selector: '.msg-error', contains: 'Срок действия карточки истёк.' },
      { kind: 'visible', selector: '.hitl-options' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'memory.save',
    title: 'Память: сохранение',
    proves: 'Мутация памяти не происходит напрямую — пользователь получает HITL-карточку.',
    api: [
      {
        key: 'memory.save',
        replies: [
          {
            json: {
              ...choiceCard({ title: 'Сохранить в память?', purpose: 'quality_review' }),
            },
          },
        ],
      },
    ],
    drive: async page => {
      await page.getByRole('button', { name: 'Память' }).click();
      await page.locator('.memory-input').fill('pref-lang');
      await page.locator('.memory-textarea').fill('Общается по-русски');
      await page.getByRole('button', { name: 'Запросить сохранение' }).click();
    },
    checks: [
      {
        kind: 'text',
        selector: '.msg.assistant .block-paragraph',
        contains: 'Сохранение в память ожидает подтверждения',
      },
      { kind: 'visible', selector: '.hitl-card' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'memory.forget',
    title: 'Память: забывание',
    proves: 'Удаление записи из памяти идёт тем же путём: HITL-карточка, а не прямой вызов.',
    api: [
      {
        key: 'memory.forget',
        replies: [
          {
            json: {
              ...choiceCard({ title: 'Забыть запись?', purpose: 'quality_review' }),
            },
          },
        ],
      },
    ],
    drive: async page => {
      await page.getByRole('button', { name: 'Память' }).click();
      await page.getByRole('tab', { name: 'Забыть' }).click();
      // Поле ровно одно — ключ записи: текст для забывания не нужен.
      await page.locator('.memory-input').fill('pref-lang');
      await page.getByRole('button', { name: 'Запросить забывание' }).click();
    },
    checks: [
      {
        kind: 'text',
        selector: '.msg.assistant .block-paragraph',
        contains: 'Забывание из памяти ожидает подтверждения',
      },
      { kind: 'visible', selector: '.hitl-card' },
      { kind: 'hidden', selector: '.memory-textarea' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'memory.extract',
    title: 'Память: извлечение из диалога',
    proves: 'consolidate = extract (transcript → medium) и назван так, чтобы не путать с promote.',
    api: [
      {
        key: 'memory.consolidate',
        replies: [
          {
            json: {
              ...choiceCard({ title: 'Извлечь факты?', purpose: 'quality_review' }),
            },
          },
        ],
      },
    ],
    drive: async page => {
      await page.getByRole('button', { name: 'Память' }).click();
      await page.getByRole('tab', { name: 'Извлечь' }).click();
      await page.getByRole('button', { name: 'Запросить извлечение' }).click();
    },
    checks: [
      { kind: 'text', selector: '.memory-hint', contains: 'sleep-time extract' },
      {
        kind: 'text',
        selector: '.msg.assistant .block-paragraph',
        contains: 'Извлечение из диалога ожидает подтверждения',
      },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'attachment.ready',
    title: 'Вложение готово',
    proves: 'Файл проходит init → upload → complete и уходит в запрос как attachment_ids.',
    api: [
      { key: 'attachments.init', replies: [{ json: attachmentTicket() }] },
      { key: 'attachments.content', replies: [{ json: uploadedAttachment() }] },
      { key: 'attachments.complete', replies: [{ json: readyAttachment() }] },
      { key: 'intents.process', replies: [{ json: formatterResult() }] },
    ],
    drive: async page => {
      await pickPdf(page, 'dogovor.pdf');
      await page.locator('.attachment-chip.is-ready').waitFor();
      await ask(page, 'Что в договоре?');
    },
    checks: [
      { kind: 'text', selector: '.msg.user .bubble-attachments', contains: 'dogovor.pdf' },
      // Чипы снимаются после отправки: файл уже в этом ходе, повторно он не уедет.
      { kind: 'hidden', selector: '.attachment-chip' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'attachment.refused',
    title: 'Вложение отклонено',
    proves: 'Отказ пайплайна виден пользователю с причиной — файл не «исчезает молча».',
    api: [
      { key: 'attachments.init', replies: [{ json: attachmentTicket() }] },
      { key: 'attachments.content', replies: [{ json: uploadedAttachment('virus.pdf') }] },
      {
        key: 'attachments.complete',
        replies: [{ json: quarantinedAttachment('malware_detected') }],
      },
    ],
    drive: async page => {
      await pickPdf(page, 'virus.pdf');
      await page.locator('.attachment-chip.is-failed').waitFor();
    },
    checks: [
      { kind: 'text', selector: '.attachment-reason', contains: 'обнаружено вредоносное ПО' },
      { kind: 'count', selector: '.attachment-chip', count: 1 },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'collapsed',
    title: 'Свёрнутая панель',
    proves:
      'close()/open() переключают состояние, отражают его в `[collapsed]` и не теряют диалог.',
    api: [],
    drive: async page => {
      await page.getByRole('button', { name: 'Свернуть: close()' }).click();
      await page.locator('.launcher').waitFor();
    },
    checks: [
      { kind: 'attr', selector: '', name: 'collapsed' },
      { kind: 'visible', selector: '.launcher' },
      { kind: 'hidden', selector: '.shell' },
      { kind: 'noEnglish' },
    ],
  },
  {
    id: 'theme.light',
    title: 'Светлая тема (opt-in хоста)',
    proves: 'Тема переключается атрибутом `data-theme`, а не системной настройкой пользователя.',
    api: [],
    drive: async page => {
      await page.getByRole('button', { name: 'Тема: светлая' }).click();
    },
    checks: [
      { kind: 'cssVar', selector: '', name: '--bg', value: '#f6f7f9' },
      { kind: 'attr', selector: '', name: 'data-theme', value: 'light' },
      { kind: 'noEnglish' },
    ],
  },
];

/** Идентификатор кадра — в имя теста, чтобы падение читалось без открытия файла. */
export function stateId(state: WidgetState): string {
  return `${state.id} — ${state.title}`;
}
