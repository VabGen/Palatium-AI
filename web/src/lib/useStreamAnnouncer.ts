/**
 * Состояние канала озвучивания на один диалог (084, W2).
 *
 * Хук держит ТОЛЬКО дедупликацию и сборку: какие блоки/куски уже объявлены, и
 * как несколько объявлений одного тика не потеряться. Сам текст строит
 * `lib/streamA11y` (чистый модуль), разметку — `LiveAnnouncer`.
 *
 * Два источника одного ответа: типизированные `block_delta` и markdown-дельты.
 * Объявлять оба значило бы прочитать ответ дважды, поэтому `ChatShell` зовёт
 * markdown-канал только пока типизированный не начался — как и в превью.
 *
 * Почему буфер, а не прямой `setAnnouncement`:
 *
 *  - SSE-парсер разбирает все кадры одного сетевого чанка в одном синхронном
 *    цикле, и React схлопывает `setState` из них в один рендер — без буфера
 *    прозвучал бы ТОЛЬКО последний блок, а предыдущие исчезли бы бесследно.
 *  - Буфер сбрасывается микрозадачей: разные чанки (разные тики) остаются
 *    разными объявлениями, один чанк с несколькими блоками — одним объявлением
 *    со всеми текстами. `aria-atomic` всё равно зачитывает слот целиком.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import type { Announcement } from '../components/LiveAnnouncer';
import type { ContentBlock, FormatterTaskResult } from '../types/contentDocument';
import {
  closedMarkdownChunks,
  describeBlock,
  describeDocumentTitle,
  describeFailure,
  describeMarkdownChunk,
  describeReady,
} from './streamA11y';

export type StreamAnnouncerApi = {
  announceTitle: (title: string) => void;
  announceBlock: (index: number, block: ContentBlock) => void;
  announceMarkdown: (accumulated: string) => void;
  announceReady: (result: FormatterTaskResult) => void;
  announceFailure: (message: string) => void;
  reset: () => void;
};

/**
 * Возвращает пару, а не один объект: `announcement` меняется на каждое
 * объявление, и объект с ним в составе ломал бы идентичность колбэков, которые
 * держат его в зависимостях (`useCallback` в `ChatShell` пересобирался бы на
 * каждый блок). API стабилен, меняется только текст.
 */
export function useStreamAnnouncer(): [Announcement | null, StreamAnnouncerApi] {
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);
  const seqRef = useRef(0);
  const pendingRef = useRef<string[]>([]);
  const flushScheduledRef = useRef(false);
  const titleAnnouncedRef = useRef(false);
  const blockIndexesRef = useRef<Set<number>>(new Set());
  const markdownChunksRef = useRef(0);
  const markdownSeenRef = useRef('');

  const flush = useCallback(() => {
    flushScheduledRef.current = false;
    const texts = pendingRef.current;
    pendingRef.current = [];
    if (texts.length === 0) return;
    seqRef.current += 1;
    setAnnouncement({ seq: seqRef.current, text: texts.join(' ') });
  }, []);

  const announce = useCallback(
    (text: string | null) => {
      const trimmed = text?.trim();
      if (!trimmed) return;
      pendingRef.current.push(trimmed);
      if (flushScheduledRef.current) return;
      flushScheduledRef.current = true;
      queueMicrotask(flush);
    },
    [flush]
  );

  const announceTitle = useCallback(
    (title: string) => {
      if (titleAnnouncedRef.current) return;
      const text = describeDocumentTitle(title);
      if (!text) return;
      titleAnnouncedRef.current = true;
      announce(text);
    },
    [announce]
  );

  const announceBlock = useCallback(
    (index: number, block: ContentBlock) => {
      // Повторный индекс (retry/replay кадра) не должен звучать дважды.
      if (blockIndexesRef.current.has(index)) return;
      blockIndexesRef.current.add(index);
      announce(describeBlock(block));
    },
    [announce]
  );

  const announceMarkdown = useCallback(
    (accumulated: string) => {
      // Аккумулятор может быть сброшен (`answer_delta` с `replace`): новый поток
      // не начинается со старого текста. Счётчик кусков тогда обнуляется, иначе
      // первое же объявление нового потока было бы проглочено.
      if (!accumulated.startsWith(markdownSeenRef.current)) markdownChunksRef.current = 0;
      markdownSeenRef.current = accumulated;

      const chunks = closedMarkdownChunks(accumulated);
      for (const chunk of chunks.slice(markdownChunksRef.current)) {
        announce(describeMarkdownChunk(chunk));
      }
      markdownChunksRef.current = Math.max(markdownChunksRef.current, chunks.length);
    },
    [announce]
  );

  const announceReady = useCallback(
    (result: FormatterTaskResult) => {
      const ready = describeReady({ requiresReview: result.requires_review });
      const title = result.output?.title;
      if (title && !titleAnnouncedRef.current) {
        // Заголовок не пришёл отдельным кадром — он звучит здесь же, ОДНИМ
        // объявлением с финалом: два `announce` подряд схлопнулись бы, и
        // заголовок потерялся бы молча.
        titleAnnouncedRef.current = true;
        const named = describeDocumentTitle(title);
        announce(named ? `${named} ${ready}` : ready);
        return;
      }
      announce(ready);
    },
    [announce]
  );

  const announceFailure = useCallback(
    (message: string) => {
      announce(describeFailure(message));
    },
    [announce]
  );

  const reset = useCallback(() => {
    titleAnnouncedRef.current = false;
    blockIndexesRef.current = new Set();
    markdownChunksRef.current = 0;
    markdownSeenRef.current = '';
    // Несброшенный буфер прошлого хода не должен прозвучать в новом.
    pendingRef.current = [];
    setAnnouncement(null);
  }, []);

  const api = useMemo(
    () => ({
      announceTitle,
      announceBlock,
      announceMarkdown,
      announceReady,
      announceFailure,
      reset,
    }),
    [announceBlock, announceFailure, announceMarkdown, announceReady, announceTitle, reset]
  );

  return [announcement, api];
}
