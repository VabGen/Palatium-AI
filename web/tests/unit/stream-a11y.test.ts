/**
 * Канал озвучивания стрима (084, W2).
 *
 * Проверяется контракт, а не «звучит ли красиво»:
 *  - проза идёт целиком, структура — формой (таблица/код не читаются построчно);
 *  - один блок = одно объявление (список не дробится);
 *  - незакрытое не объявляется вообще — ни абзац, ни fence;
 *  - повторный кадр/кусок не звучит дважды.
 *
 * Поведение VoiceOver/NVDA этим тестом не проверяется и не может: он живёт в
 * ручном чек-листе `web/e2e/` рядом с axe-гейтом.
 */
import { describe, expect, it } from 'vitest';

import {
  MAX_ENUMERATED_ITEMS,
  closedMarkdownChunks,
  describeBlock,
  describeDocumentTitle,
  describeFailure,
  describeMarkdownChunk,
  describeReady,
  plainInline,
} from '../../src/lib/streamA11y';
import { setI18nLocale, t } from '../../src/i18n';
import type { ContentBlock } from '../../src/types/contentDocument';

describe('plainInline', () => {
  it('keeps the words and drops the markup', () => {
    expect(plainInline('**Важно:** см. [договор](https://edo/x) и `код`')).toBe(
      'Важно: см. договор и код'
    );
  });

  it('drops icon tokens and HITL tags instead of speaking their names', () => {
    expect(plainInline('Статус <icon name="check"/> готов <hitl-action id="x"/>')).toBe(
      'Статус готов'
    );
  });

  it('removes heading and list markers but not hyphenated words', () => {
    expect(plainInline('## Итоги\n- первое\n- второе')).toBe('Итоги первое второе');
    expect(plainInline('срок — 3 дня')).toBe('срок — 3 дня');
  });
});

describe('describeBlock', () => {
  it('announces a paragraph in full', () => {
    const text = 'Ответ достаточно длинный, чтобы его нельзя было назвать «кратким».';
    expect(describeBlock({ type: 'paragraph', text })).toBe(text);
  });

  it('labels a heading so it does not sound like another paragraph', () => {
    expect(describeBlock({ type: 'heading', level: 2, text: 'Отличия' })).toBe(
      t('a11y.heading', { text: 'Отличия' })
    );
  });

  it('announces a list once, not once per item', () => {
    const block: ContentBlock = {
      type: 'list',
      style: 'ordered',
      items: [{ text: 'Первое' }, { text: 'Второе' }],
    };
    const announcement = describeBlock(block);

    expect(announcement).toBe(t('a11y.list', { count: 2, items: 'Первое; Второе' }));
    // Один вызов aria-live на блок: склейка, а не два массива строк.
    expect(announcement).not.toContain('\n');
  });

  it('caps long enumerations and says how many were left out', () => {
    const items = Array.from({ length: MAX_ENUMERATED_ITEMS + 2 }, (_, index) => ({
      text: `Пункт ${index + 1}`,
    }));
    const announcement = describeBlock({ type: 'list', style: 'unordered', items }) ?? '';

    expect(announcement).toContain('Пункт 1');
    expect(announcement).toContain(`Пункт ${MAX_ENUMERATED_ITEMS}`);
    expect(announcement).not.toContain(`Пункт ${MAX_ENUMERATED_ITEMS + 1}`);
    expect(announcement).toContain(t('a11y.listMore', { count: 2 }));
  });

  it('describes a table by shape, not by cells', () => {
    const announcement =
      describeBlock({
        type: 'table',
        columns: ['Поле', 'Было', 'Стало'],
        rows: [
          ['значение-из-ячейки', '1', '2'],
          ['b', '3', '4'],
        ],
      }) ?? '';

    // Заголовки столбцов полезны для ориентации; содержимое строк — нет.
    expect(announcement).toContain(
      t('a11y.table', { cols: 3, rows: 2, columns: 'Поле, Было, Стало' })
    );
    expect(announcement).not.toContain('значение-из-ячейки');
  });

  it('describes code by language and size', () => {
    expect(describeBlock({ type: 'code', language: 'python', content: 'a\nb\nc' })).toBe(
      t('a11y.code', { language: 'python', lines: 3 })
    );
    expect(describeBlock({ type: 'code', language: '', content: 'a' })).toBe(
      t('a11y.codeNoLanguage', { lines: 1 })
    );
  });

  it('speaks the tone of a callout before its text', () => {
    const announcement =
      describeBlock({ type: 'callout', tone: 'warning', title: 'Риск', body: 'Проверьте' }) ?? '';

    expect(announcement).toContain(t('a11y.tone.warning'));
    expect(announcement).toContain('Риск. Проверьте');
  });

  it('says nothing for a divider', () => {
    expect(describeBlock({ type: 'divider' })).toBeNull();
  });
});

describe('closedMarkdownChunks', () => {
  it('does not announce an open paragraph', () => {
    expect(closedMarkdownChunks('Первая половина фразы')).toEqual([]);
  });

  it('announces a paragraph once it is closed by a blank line', () => {
    expect(closedMarkdownChunks('Готово.\n\nДальше пишу')).toEqual([
      { kind: 'prose', text: 'Готово.' },
    ]);
  });

  it('treats a closed fence as one code chunk and never as prose', () => {
    const chunks = closedMarkdownChunks('Текст.\n\n```python\nprint("a")\n```\n\nХвост');
    expect(chunks).toEqual([
      { kind: 'prose', text: 'Текст.' },
      { kind: 'code', text: 'print("a")', language: 'python' },
    ]);
  });

  it('ignores an unclosed fence entirely', () => {
    expect(closedMarkdownChunks('```python\nprint("a")\n')).toEqual([]);
  });

  it('keeps a multi-line prose block as one chunk', () => {
    expect(closedMarkdownChunks('Строка один\nстрока два\n\n')).toEqual([
      { kind: 'prose', text: 'Строка один строка два' },
    ]);
  });

  it('describes a code chunk by shape', () => {
    expect(describeMarkdownChunk({ kind: 'code', text: 'a\nb', language: 'ts' })).toBe(
      t('a11y.code', { language: 'ts', lines: 2 })
    );
  });
});

describe('документ и финал', () => {
  it('names the answer before the first block', () => {
    expect(describeDocumentTitle('Черновик письма')).toBe(
      t('a11y.docTitle', { title: 'Черновик письма' })
    );
    expect(describeDocumentTitle('   ')).toBe('');
  });

  it('says review is required instead of a plain "ready"', () => {
    expect(describeReady({ requiresReview: false })).toBe(t('a11y.ready'));
    expect(describeReady({ requiresReview: true })).toBe(t('a11y.readyReview'));
  });

  it('announces an error with the message', () => {
    expect(describeFailure('Провайдер недоступен')).toBe(
      t('a11y.error', { message: 'Провайдер недоступен' })
    );
  });

  it('uses the English dictionary when the host is English', () => {
    setI18nLocale('en-US');
    try {
      expect(describeReady({ requiresReview: false })).toBe('Answer ready.');
    } finally {
      setI18nLocale('ru-RU');
    }
  });
});
