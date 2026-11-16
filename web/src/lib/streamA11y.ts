/**
 * Что именно слышит пользователь скринридера во время стрима (084, W2).
 *
 * Визуальная лента объявляет себя `role="log"`, но с `aria-live="off"`: если
 * оставить polite, каждый `block_delta` (а в markdown-пути — каждый чанк)
 * превращается в лавину перечитываний. Поэтому текст идёт в ОТДЕЛЬНЫЙ канал, и
 * здесь живёт правило перевода блока в речь — без DOM и без React, чтобы его
 * можно было проверить тестом без браузера и скринридера.
 *
 * Принципы (они же причины, почему функция выглядит именно так):
 *
 *  1. **Проза — целиком.** Абзац/пункт ответа — то, ради чего пользователь здесь;
 *     обрезать его «для краткости» значит отдать неполный ответ тому, кто читает
 *     только на слух.
 *  2. **Структура — формой, а не содержимым.** Таблица на 40 строк и блок кода на
 *     200 строк на слух бесполезны: объявляется «сколько чего», а содержимое
 *     доступно в самом документе, куда пользователь перейдёт.
 *  3. **Один блок — одно объявление.** Список/шаги/поля не дробятся на элементы,
 *     иначе `aria-live` зачитывает их по одному и вперемешку с кликами.
 *  4. **Ничего не выдумывать.** Разделитель (`divider`) не объявляется вовсе:
 *     «линия» — визуальный приём, а не содержание.
 */
import { t } from '../i18n';
import type { ContentBlock, ListItem, StepItem } from '../types/contentDocument';

/**
 * Сколько элементов перечисления озвучивать. Дальше — «и ещё N»: полный список
 * остаётся в документе, а канал не превращается в минуту монотонного чтения.
 */
export const MAX_ENUMERATED_ITEMS = 5;

/** Максимум символов для не-прозаических блоков (код, формула): остальное — формой. */
export const MAX_LITERAL_CHARS = 240;

export type ClosedMarkdownChunk = {
  kind: 'prose' | 'code';
  text: string;
  language?: string;
};

/**
 * Markdown → плоский текст для озвучивания.
 *
 * Это НЕ рендер и не санитайзер: строка нужна только для слуха, поэтому
 * разметка снимается, а не экранируется. Неизвестные конструкции остаются как
 * есть — лучше услышать `~~x~~`, чем потерять слово.
 */
export function plainInline(markdown: string): string {
  return (
    markdown
      // Иконки — декоративные токены, их «имя» ничего не сообщает слушателю.
      .replace(/<icon\s+(?:name|x)="[a-z_]+"\s*\/>/gi, ' ')
      .replace(/<\/?hitl-[^>]*>/gi, ' ')
      .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
      .replace(/\[([^\]]+)]\([^)]*\)/g, '$1')
      .replace(/`{1,3}([^`]+)`{1,3}/g, '$1')
      .replace(/(\*\*|__)(.*?)\1/g, '$2')
      .replace(/(\*|_)(.*?)\1/g, '$2')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/^\s*\d+[.)]\s+/gm, '')
      .replace(/^\s*>\s?/gm, '')
      .replace(/\s+/g, ' ')
      .trim()
  );
}

/** «Раздел: …», чтобы заголовок не сливался с первым абзацем в потоке речи. */
export function describeDocumentTitle(title: string): string {
  const text = plainInline(title);
  return text ? t('a11y.docTitle', { title: text }) : '';
}

function enumerate<T>(items: readonly T[], render: (item: T, index: number) => string): string {
  const head = items.slice(0, MAX_ENUMERATED_ITEMS).map(render).filter(Boolean).join('; ');
  const rest = items.length - MAX_ENUMERATED_ITEMS;
  return rest > 0 ? `${head}; ${t('a11y.listMore', { count: rest })}` : head;
}

const listItems = (items: readonly ListItem[]): string =>
  enumerate(items, item => plainInline(item.text));

const stepItems = (items: readonly StepItem[]): string =>
  enumerate(
    items,
    (item, index) =>
      `${index + 1}) ${plainInline(item.title)}${item.body ? ` — ${plainInline(item.body)}` : ''}`
  );

const TONE_KEY = {
  info: 'a11y.tone.info',
  success: 'a11y.tone.success',
  warning: 'a11y.tone.warning',
  danger: 'a11y.tone.danger',
} as const;

/**
 * Первое, что слышно про ответ — «Ответ: <название>», — до первого блока.
 * Пустой заголовок не объявляется: тишина честнее выдуманного названия.
 */
export function describeBlock(block: ContentBlock): string | null {
  switch (block.type) {
    case 'heading':
      return t('a11y.heading', { text: plainInline(block.text) });
    case 'paragraph':
      return plainInline(block.text);
    case 'list': {
      const items = listItems(block.items);
      return items ? t('a11y.list', { count: block.items.length, items }) : null;
    }
    case 'steps': {
      const items = stepItems(block.items);
      return items ? t('a11y.steps', { count: block.items.length, items }) : null;
    }
    case 'kv': {
      const items = enumerate(
        block.items,
        item => `${plainInline(item.label)} — ${plainInline(item.value)}`
      );
      return items ? t('a11y.kv', { items }) : null;
    }
    case 'table': {
      const columns = block.columns.map(plainInline).join(', ');
      return t('a11y.table', {
        cols: block.columns.length,
        rows: block.rows.length,
        columns,
      });
    }
    case 'code': {
      const lines = block.content.split('\n').length;
      const language = block.language.trim();
      return language ? t('a11y.code', { language, lines }) : t('a11y.codeNoLanguage', { lines });
    }
    case 'formula':
      return t('a11y.formula', { latex: block.latex.trim().slice(0, MAX_LITERAL_CHARS) });
    case 'callout': {
      const title = block.title ? `${plainInline(block.title)}. ` : '';
      const body = plainInline(block.body);
      const text = `${title}${body}`.trim();
      return text ? t('a11y.callout', { tone: t(TONE_KEY[block.tone]), text }) : null;
    }
    case 'chart': {
      const shape = t('a11y.chart', { series: block.series.length });
      const title = block.title ? plainInline(block.title) : '';
      return title ? `${shape}. ${title}` : shape;
    }
    case 'widget': {
      const title = block.title ? plainInline(block.title) : '';
      return title ? t('a11y.widget', { title }) : t('a11y.widgetUntitled');
    }
    case 'divider':
      // Линия — визуальный разделитель, а не содержание.
      return null;
    default:
      return null;
  }
}

/**
 * Закрытые куски markdown-стрима.
 *
 * Пока проза не закрыта пустой строкой, её нельзя объявлять: пользователь
 * услышал бы половину фразы, а затем её продолжение как «новое». Открытый
 * fence тоже не считается закрытым — код читается формой, а не по строкам.
 */
export function closedMarkdownChunks(markdown: string): ClosedMarkdownChunk[] {
  const chunks: ClosedMarkdownChunk[] = [];
  let prose: string[] = [];
  let fence: { body: string[]; language: string } | null = null;

  const flushProse = (): void => {
    if (prose.length === 0) return;
    const text = plainInline(prose.join('\n'));
    prose = [];
    if (text) chunks.push({ kind: 'prose', text });
  };

  for (const line of markdown.split('\n')) {
    if (fence) {
      if (/^\s*(```|~~~)\s*$/.test(line)) {
        chunks.push({ kind: 'code', text: fence.body.join('\n'), language: fence.language });
        fence = null;
      } else {
        fence.body.push(line);
      }
      continue;
    }
    const opening = /^\s*(```|~~~)\s*([\w+#.-]*)/.exec(line);
    if (opening) {
      flushProse();
      fence = { body: [], language: opening[2] ?? '' };
      continue;
    }
    if (line.trim() === '') {
      flushProse();
      continue;
    }
    prose.push(line);
  }
  // Открытые проза и fence намеренно не отдаются: они ещё не готовы.
  return chunks;
}

/** Речь для одного закрытого markdown-куска. */
export function describeMarkdownChunk(chunk: ClosedMarkdownChunk): string | null {
  if (chunk.kind === 'prose') return chunk.text || null;
  const lines = chunk.text.split('\n').length;
  const language = chunk.language?.trim() ?? '';
  return language ? t('a11y.code', { language, lines }) : t('a11y.codeNoLanguage', { lines });
}

/** Финальный сигнал: ответ перестал меняться, дальше — чтение документа. */
export function describeReady(options: { requiresReview: boolean }): string {
  return options.requiresReview ? t('a11y.readyReview') : t('a11y.ready');
}

export function describeFailure(message: string): string {
  const text = plainInline(message).slice(0, MAX_LITERAL_CHARS);
  return t('a11y.error', { message: text });
}
