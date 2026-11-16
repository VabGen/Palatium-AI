/**
 * Канал озвучивания: дедупликация, батчинг и разметка live-региона (084, W2).
 *
 * Здесь проверяется то, что нельзя проверить чистыми функциями:
 *  - повторный кадр SSE не звучит дважды;
 *  - несколько блоков из ОДНОГО сетевого чанка не теряются (иначе React
 *    схлопнул бы `setState` и прозвучал бы только последний);
 *  - регион остаётся смонтированным и меняет только содержимое: переключение
 *    `aria-live` после появления текста часть пар «браузер + скринридер» не
 *    объявляет вовсе.
 */
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LiveAnnouncer, type Announcement } from '../../src/components/LiveAnnouncer';
import { useStreamAnnouncer, type StreamAnnouncerApi } from '../../src/lib/useStreamAnnouncer';
import { t } from '../../src/i18n';
import type { FormatterTaskResult } from '../../src/types/contentDocument';

type Harness = { api: StreamAnnouncerApi };

function AnnouncerHarness({ onReady }: { onReady: (value: Harness) => void }) {
  const [announcement, api] = useStreamAnnouncer();
  onReady({ api });
  return <LiveAnnouncer announcement={announcement} />;
}

function mount(): Harness {
  let harness: Harness | null = null;
  render(<AnnouncerHarness onReady={value => (harness = value)} />);
  if (!harness) throw new Error('harness was not initialised');
  return harness;
}

function regionTexts(): string[] {
  return screen.getAllByRole('status').map(node => node.textContent ?? '');
}

function spokenText(): string {
  return regionTexts().join('').trim();
}

/** Действие + сброс микрозадачи буфера объявлений (см. `useStreamAnnouncer`). */
async function speak(run: () => void): Promise<void> {
  await act(async () => {
    run();
  });
}

const RESULT: FormatterTaskResult = {
  task_id: 'task-1',
  agent_role: 'formatter',
  status: 'success',
  confidence: 0.9,
  requires_review: false,
  error: null,
  output: {
    schema_version: 1,
    locale: 'ru-RU',
    title: 'Итоги',
    blocks: [{ type: 'paragraph', text: 'Готово.' }],
    actions: [],
    meta: { confidence: 0.9, requires_review: false, source_refs: [] },
  },
  hitl_cards: [],
};

describe('LiveAnnouncer', () => {
  it('keeps two status regions mounted and never leaves live announcements off', () => {
    const { rerender } = render(<LiveAnnouncer announcement={{ seq: 1, text: 'Первый' }} />);

    expect(screen.getAllByRole('status')).toHaveLength(2);
    for (const region of screen.getAllByRole('status')) {
      expect(region).toHaveAttribute('aria-live', 'polite');
      expect(region).toHaveAttribute('aria-atomic', 'true');
      expect(region).toHaveClass('sr-only', 'live-announcer');
    }

    rerender(<LiveAnnouncer announcement={{ seq: 2, text: 'Второй' }} />);
    // Регионов по-прежнему два: смена текста не пересоздаёт разметку.
    expect(screen.getAllByRole('status')).toHaveLength(2);
    expect(spokenText()).toBe('Второй');
  });

  it('alternates slots so an identical repeated text still mutates the DOM', () => {
    const first: Announcement = { seq: 1, text: 'Повтор' };
    const second: Announcement = { seq: 2, text: 'Повтор' };
    const { rerender } = render(<LiveAnnouncer announcement={first} />);

    const before = regionTexts();
    rerender(<LiveAnnouncer announcement={second} />);
    const after = regionTexts();

    expect(spokenText()).toBe('Повтор');
    // Тот же текст оказался в ДРУГОМ узле — иначе скринридер не увидел бы изменения.
    expect(after).not.toEqual(before);
  });

  it('renders nothing to speak before the first announcement', () => {
    render(<LiveAnnouncer announcement={null} />);
    expect(spokenText()).toBe('');
  });
});

describe('useStreamAnnouncer', () => {
  it('announces a closed block once even if the frame is replayed', async () => {
    const { api } = mount();
    const block = { type: 'paragraph', text: 'Первый блок' } as const;

    await speak(() => api.announceBlock(0, block));
    const first = regionTexts();
    expect(spokenText()).toBe('Первый блок');

    await speak(() => api.announceBlock(0, block));
    expect(regionTexts()).toEqual(first);
  });

  it('does not speak a divider (nothing is said, but the index is spent)', async () => {
    const { api } = mount();

    await speak(() => api.announceBlock(0, { type: 'divider' }));
    expect(spokenText()).toBe('');

    await speak(() => api.announceBlock(1, { type: 'paragraph', text: 'Текст' }));
    expect(spokenText()).toBe('Текст');
  });

  it('keeps every block of one network chunk instead of only the last', async () => {
    const { api } = mount();

    // Так их отдаёт SSE-парсер: один синхронный цикл, три кадра, один рендер.
    await speak(() => {
      api.announceBlock(0, { type: 'paragraph', text: 'Первый' });
      api.announceBlock(1, { type: 'list', style: 'ordered', items: [{ text: 'Второй' }] });
      api.announceBlock(2, { type: 'paragraph', text: 'Третий' });
    });

    expect(spokenText()).toContain('Первый');
    expect(spokenText()).toContain('Второй');
    expect(spokenText()).toContain('Третий');
  });

  it('announces markdown chunks incrementally without repeats', async () => {
    const { api } = mount();

    await speak(() => api.announceMarkdown('Первая часть'));
    expect(spokenText()).toBe('');

    await speak(() => api.announceMarkdown('Первая часть.\n\nВторая'));
    expect(spokenText()).toBe('Первая часть.');

    // Продолжение того же потока: уже сказанное не повторяется.
    await speak(() => api.announceMarkdown('Первая часть.\n\nВторая.\n\nТретья'));
    expect(spokenText()).toBe('Вторая.');
  });

  it('announces both paragraphs closed in one delta', async () => {
    const { api } = mount();

    await speak(() => api.announceMarkdown('Раз.\n\nДва.\n\nТри'));
    expect(spokenText()).toContain('Раз.');
    expect(spokenText()).toContain('Два.');
  });

  it('re-announces from scratch after an accumulator reset', async () => {
    const { api } = mount();

    await speak(() => api.announceMarkdown('Старое.\n\nСтарое-2'));
    expect(spokenText()).toBe('Старое.');

    // `answer_delta` с `replace` сбрасывает аккумулятор: текст начинается заново,
    // и первое объявление нового потока не должно быть проглочено счётчиком.
    await speak(() => api.announceMarkdown('Новое.\n\n'));
    expect(spokenText()).toBe('Новое.');
  });

  it('speaks the title once, even when it arrives both as a frame and in the result', async () => {
    const { api } = mount();

    await speak(() => api.announceTitle('Итоги'));
    expect(spokenText()).toBe(t('a11y.docTitle', { title: 'Итоги' }));

    await speak(() => api.announceReady(RESULT));
    expect(spokenText()).toBe(t('a11y.ready'));
  });

  it('folds the result title into the final announcement when no frame carried it', async () => {
    const { api } = mount();

    await speak(() => api.announceReady(RESULT));
    // Одно объявление: заголовок и финал вместе — не два `setState` подряд.
    expect(spokenText()).toBe(`${t('a11y.docTitle', { title: 'Итоги' })} ${t('a11y.ready')}`);
  });

  it('says review is required when the result asks for it', async () => {
    const { api } = mount();

    await speak(() => api.announceReady({ ...RESULT, requires_review: true }));
    expect(spokenText()).toContain(t('a11y.readyReview'));
  });

  it('speaks a failure instead of leaving the last success hanging', async () => {
    const { api } = mount();

    await speak(() => api.announceReady(RESULT));
    await speak(() => api.announceFailure('Стрим оборвался'));

    expect(spokenText()).toBe(t('a11y.error', { message: 'Стрим оборвался' }));
  });

  it('forgets the previous turn on reset', async () => {
    const { api } = mount();

    await speak(() => api.announceBlock(0, { type: 'paragraph', text: 'Прошлый ход' }));
    await speak(() => api.reset());
    expect(spokenText()).toBe('');

    // Индекс 0 снова «свободен» — новый ход начинается с нуля.
    await speak(() => api.announceBlock(0, { type: 'paragraph', text: 'Новый ход' }));
    expect(spokenText()).toBe('Новый ход');
  });
});
