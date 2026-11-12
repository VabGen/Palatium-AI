import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { fetchDialogTurns } from '../api/client';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import { HistoryEmptySearchArt } from '../icons/HistoryEmptySearch';
import {
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconPencil,
  IconPinTop,
  IconSearch,
  IconTrash,
  IconX,
} from '../icons/kimiStroke';
import { attachmentDisplayName } from '../lib/attachments';
import { t, formatDateTime } from '../i18n';
import type { MessageKey } from '../i18n/messages';
import {
  extractHistoryPreview,
  type HistoryFileChip,
  type HistoryPreview,
} from '../lib/historyPreview';

export type ChatHistoryItem = {
  id: string;
  title: string;
  projectId?: string | null;
  /** ISO timestamp from `GET /sessions`; absent rows fall into "Earlier". */
  updatedAt?: string;
  /** Optional live-thread seed so the open chat paints before turns hydrate. */
  snippet?: string | null;
  files?: readonly HistoryFileChip[];
};

export type ChatHistoryPageProps = {
  threads: readonly ChatHistoryItem[];
  activeThreadId: string;
  pinnedThreadIds?: readonly string[];
  userId?: string | null;
  orgId?: string | null;
  onOpenThread: (id: string) => void;
  onNewChat: () => void;
  onClose: () => void;
  onRenameThread?: (id: string) => void;
  onPinThread?: (id: string) => void;
  onDeleteThread?: (id: string, title: string) => void;
  /** Bulk archive — confirms in the parent shell (HITL dialog). */
  onDeleteThreads?: (items: readonly { id: string; title: string }[]) => void;
};

type GroupId = 'today' | 'yesterday' | 'week' | 'month' | 'earlier';

type ScrollEdges = { start: boolean; end: boolean };

const GROUP_ORDER: readonly GroupId[] = ['today', 'yesterday', 'week', 'month', 'earlier'];

const GROUP_LABEL: Record<GroupId, MessageKey> = {
  today: 'historyPage.group.today',
  yesterday: 'historyPage.group.yesterday',
  week: 'historyPage.group.week',
  month: 'historyPage.group.month',
  earlier: 'historyPage.group.earlier',
};

/** Cap concurrent turn fetches so opening history does not stampede the API. */
const PREVIEW_CONCURRENCY = 4;
const PREVIEW_TURN_LIMIT = 12;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Calendar-day bucket, not a rolling 24h window (kimi.ai groups by day). */
export function historyGroupFor(iso: string | undefined, now = new Date()): GroupId {
  if (!iso) return 'earlier';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'earlier';
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return 'week';
  if (days < 30) return 'month';
  return 'earlier';
}

function matchesQuery(thread: ChatHistoryItem, query: string, preview?: HistoryPreview): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  if (thread.title.toLowerCase().includes(needle)) return true;
  const snippet = (preview?.snippet ?? thread.snippet ?? '').toLowerCase();
  if (snippet.includes(needle)) return true;
  const files = preview?.files ?? thread.files ?? [];
  return files.some(file => file.filename.toLowerCase().includes(needle));
}

/**
 * Right-hand meta — kimi.ai `.history-chat-meta`:
 * clock for today, relative for yesterday, short date afterwards.
 */
function metaLabel(iso: string | undefined, now: Date): string | null {
  if (!iso) return null;
  const bucket = historyGroupFor(iso, now);
  if (bucket === 'today') {
    return formatDateTime(iso, { hour: '2-digit', minute: '2-digit' });
  }
  if (bucket === 'yesterday') return t('historyPage.group.yesterday');
  return formatDateTime(iso, { day: 'numeric', month: 'short' });
}

/**
 * Horizontal file strip — kimi.ai history carousel:
 * edge fade + frosted chevrons (both directions), like product-chips.
 */
function HistoryFileRail({ files }: { files: readonly HistoryFileChip[] }): ReactElement {
  const scrollerRef = useRef<HTMLUListElement>(null);
  const watchRef = useRef<number | null>(null);
  const timeoutRef = useRef<number[]>([]);
  const [edges, setEdges] = useState<ScrollEdges>({ start: false, end: false });

  const syncOverflow = useCallback(() => {
    const node = scrollerRef.current;
    if (!node) return;
    const max = node.scrollWidth - node.clientWidth;
    const start = node.scrollLeft > 1;
    const end = max > 1 && node.scrollLeft < max - 1;
    setEdges(previous =>
      previous.start === start && previous.end === end ? previous : { start, end }
    );
  }, []);

  const watchScroll = useCallback(() => {
    if (watchRef.current !== null) cancelAnimationFrame(watchRef.current);
    const startedAt = performance.now();
    const step = () => {
      syncOverflow();
      watchRef.current = performance.now() - startedAt < 700 ? requestAnimationFrame(step) : null;
    };
    watchRef.current = requestAnimationFrame(step);
    if (timeoutRef.current.length) timeoutRef.current.forEach(clearTimeout);
    timeoutRef.current = [120, 320, 600].map(delay => window.setTimeout(syncOverflow, delay));
  }, [syncOverflow]);

  useEffect(() => {
    const node = scrollerRef.current;
    if (!node) return;
    const frame = requestAnimationFrame(syncOverflow);
    node.addEventListener('scroll', syncOverflow, { passive: true });
    const observer =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(syncOverflow);
    observer?.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      if (watchRef.current !== null) cancelAnimationFrame(watchRef.current);
      timeoutRef.current.forEach(clearTimeout);
      timeoutRef.current = [];
      node.removeEventListener('scroll', syncOverflow);
      observer?.disconnect();
    };
  }, [files, syncOverflow]);

  const scrollBy = (direction: -1 | 1) => {
    const node = scrollerRef.current;
    if (!node) return;
    node.scrollBy({
      left: direction * Math.max(180, node.clientWidth * 0.7),
      behavior: 'smooth',
    });
    watchScroll();
  };

  return (
    <div
      className={`chat-history__files-wrap${edges.end ? ' has-end' : ''}${
        edges.start ? ' has-start' : ''
      }`}
    >
      <ul ref={scrollerRef} className="chat-history__files" aria-label={t('attach.sources')}>
        {files.map(file => (
          <li
            key={file.filename}
            className="chat-history__file"
            data-name-tip={file.filename}
            data-name-tip-side="top"
          >
            <span className="chat-history__file-icon" aria-hidden>
              <AttachmentFileIcon kind={attachmentFileKind(file.filename)} size={40} />
            </span>
            <span className="chat-history__file-text">
              <span className="chat-history__file-name">
                {attachmentDisplayName(file.filename)}
              </span>
              {file.meta ? <span className="chat-history__file-meta">{file.meta}</span> : null}
            </span>
          </li>
        ))}
      </ul>
      {edges.start ? (
        <button
          type="button"
          className="chat-history__files-arrow chat-history__files-arrow--prev"
          aria-label={t('historyPage.prevFiles')}
          onClick={event => {
            event.preventDefault();
            event.stopPropagation();
            scrollBy(-1);
          }}
          onPointerDown={event => event.stopPropagation()}
        >
          <span className="chat-history__files-arrow-btn">
            <IconChevronLeft size={16} />
          </span>
        </button>
      ) : null}
      {edges.end ? (
        <button
          type="button"
          className="chat-history__files-arrow chat-history__files-arrow--next"
          aria-label={t('historyPage.moreFiles')}
          onClick={event => {
            event.preventDefault();
            event.stopPropagation();
            scrollBy(1);
          }}
          onPointerDown={event => event.stopPropagation()}
        >
          <span className="chat-history__files-arrow-btn">
            <IconChevronRight size={16} />
          </span>
        </button>
      ) : null}
    </div>
  );
}

type HistoryChatRowProps = {
  thread: ChatHistoryItem;
  title: string;
  active: boolean;
  pinned: boolean;
  selected: boolean;
  selecting: boolean;
  meta: string | null;
  snippet: string | null;
  files: readonly HistoryFileChip[];
  onOpen: () => void;
  onToggleSelected: () => void;
  onRename?: () => void;
  onPin?: () => void;
  onDelete?: () => void;
};

/**
 * Pointer-driven hover (not CSS `:hover`) — Windows sticky :hover was leaving
 * the wash / actions / select circle on after the cursor left.
 */
function HistoryChatRow({
  thread,
  title,
  active,
  pinned,
  selected,
  selecting,
  meta,
  snippet,
  files,
  onOpen,
  onToggleSelected,
  onRename,
  onPin,
  onDelete,
}: HistoryChatRowProps): ReactElement {
  const [hovered, setHovered] = useState(false);

  return (
    <li
      className={`chat-history__row${selected ? ' is-selected' : ''}${hovered ? ' is-hover' : ''}`}
      onPointerEnter={event => {
        if (event.pointerType === 'touch') return;
        setHovered(true);
      }}
      onPointerLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className={`chat-history__select${selected ? ' is-checked' : ''}`}
        aria-pressed={selected}
        aria-label={
          selected
            ? t('historyPage.deselectChat', { title })
            : t('historyPage.selectChat', { title })
        }
        onClick={event => {
          event.stopPropagation();
          onToggleSelected();
        }}
      >
        {selected ? <IconCheck size={14} /> : null}
      </button>

      <div
        className={`chat-history__card${active ? ' is-active' : ''}${
          selected ? ' is-selected' : ''
        }${hovered ? ' is-hover' : ''}`}
        data-thread-id={thread.id}
        role="link"
        tabIndex={0}
        aria-current={active ? 'page' : undefined}
        aria-label={title}
        onClick={() => {
          if (selecting) {
            onToggleSelected();
            return;
          }
          onOpen();
        }}
        onKeyDown={event => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          if (selecting) {
            onToggleSelected();
            return;
          }
          onOpen();
        }}
      >
        <div className="chat-history__card-head">
          <div className="chat-history__card-title-row">
            <span className="chat-history__card-title">{title}</span>
            {onRename && !selecting ? (
              <button
                type="button"
                className="chat-history__title-edit icon-hover"
                aria-label={t('thread.rename')}
                title={t('thread.rename')}
                onClick={event => {
                  event.stopPropagation();
                  onRename();
                }}
              >
                <IconPencil size={16} />
              </button>
            ) : null}
          </div>
          {meta ? <span className="chat-history__card-meta">{meta}</span> : null}
          {!selecting ? (
            <div className="chat-history__card-actions" role="group">
              {onPin ? (
                <button
                  type="button"
                  className={`chat-history__action icon-hover${pinned ? ' is-active' : ''}`}
                  aria-label={pinned ? t('thread.unpinTop') : t('thread.pinTop')}
                  title={pinned ? t('thread.unpinTop') : t('thread.pinTop')}
                  onClick={event => {
                    event.stopPropagation();
                    onPin();
                  }}
                >
                  <IconPinTop size={18} />
                </button>
              ) : null}
              {onDelete ? (
                <button
                  type="button"
                  className="chat-history__action chat-history__action--danger icon-hover"
                  aria-label={t('thread.delete')}
                  title={t('thread.delete')}
                  onClick={event => {
                    event.stopPropagation();
                    onDelete();
                  }}
                >
                  <IconTrash size={18} />
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        {snippet ? <p className="chat-history__card-snippet">{snippet}</p> : null}
        {files.length > 0 ? <HistoryFileRail files={files} /> : null}
      </div>
    </li>
  );
}

/**
 * Kimi `/chat/history` — 800px column, search capsule, date-grouped cards,
 * file carousel, multi-select + floating bulk bar.
 */
export function ChatHistoryPage({
  threads,
  activeThreadId,
  pinnedThreadIds = [],
  userId,
  orgId,
  onOpenThread,
  onNewChat,
  onClose,
  onRenameThread,
  onPinThread,
  onDeleteThread,
  onDeleteThreads,
}: ChatHistoryPageProps) {
  const [query, setQuery] = useState('');
  const [previews, setPreviews] = useState<Record<string, HistoryPreview>>({});
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(() => new Set());
  const loadedIdsRef = useRef(new Set<string>());

  /** Rows without a server timestamp still belong to today only when it is the live chat. */
  const now = useMemo(() => new Date(), []);
  const nowIso = useMemo(() => now.toISOString(), [now]);
  const threadIdsKey = useMemo(() => threads.map(thread => thread.id).join('|'), [threads]);
  const aliveIds = useMemo(() => new Set(threads.map(thread => thread.id)), [threads]);
  /** Selection ∩ current shelf — no effect sync (084 / set-state-in-effect). */
  const selectedAlive = useMemo(() => {
    const next = new Set<string>();
    for (const id of selectedIds) {
      if (aliveIds.has(id)) next.add(id);
    }
    return next;
  }, [aliveIds, selectedIds]);
  const selecting = selectedAlive.size > 0;

  useEffect(() => {
    let cancelled = false;
    const pending = threads
      .map(thread => thread.id)
      .filter(id => {
        const seeded = threads.find(row => row.id === id);
        const hasSeed =
          Boolean(seeded?.snippet?.trim()) || Boolean(seeded?.files && seeded.files.length > 0);
        if (hasSeed) {
          loadedIdsRef.current.add(id);
          return false;
        }
        return !loadedIdsRef.current.has(id);
      });

    if (pending.length === 0) return;

    for (const id of pending) loadedIdsRef.current.add(id);

    const run = async () => {
      let cursor = 0;
      const workers = Array.from(
        { length: Math.min(PREVIEW_CONCURRENCY, pending.length) },
        async () => {
          while (cursor < pending.length) {
            const index = cursor;
            cursor += 1;
            const threadId = pending[index];
            if (!threadId) continue;
            try {
              const turns = await fetchDialogTurns(threadId, PREVIEW_TURN_LIMIT, userId, orgId);
              if (cancelled) return;
              const preview = extractHistoryPreview(turns);
              setPreviews(prev => ({ ...prev, [threadId]: preview }));
            } catch {
              if (cancelled) return;
              setPreviews(prev => ({ ...prev, [threadId]: { snippet: null, files: [] } }));
            }
          }
        }
      );
      await Promise.all(workers);
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [threadIdsKey, threads, userId, orgId]);

  const groups = useMemo(() => {
    const buckets = new Map<GroupId, ChatHistoryItem[]>();
    for (const thread of threads) {
      const preview = previews[thread.id];
      if (!matchesQuery(thread, query, preview)) continue;
      const timestamp = thread.updatedAt ?? (thread.id === activeThreadId ? nowIso : undefined);
      const key = historyGroupFor(timestamp);
      const list = buckets.get(key);
      if (list) list.push(thread);
      else buckets.set(key, [thread]);
    }
    return GROUP_ORDER.filter(id => buckets.has(id)).map(id => ({
      id,
      items: buckets.get(id) ?? [],
    }));
  }, [activeThreadId, nowIso, previews, query, threads]);

  const total = groups.reduce((sum, group) => sum + group.items.length, 0);

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const requestBulkDelete = useCallback(() => {
    const items = threads
      .filter(thread => selectedAlive.has(thread.id))
      .map(thread => ({
        id: thread.id,
        title: thread.title.trim() || t('sidebar.untitled'),
      }));
    if (items.length === 0) return;
    if (onDeleteThreads) {
      onDeleteThreads(items);
      clearSelection();
      return;
    }
    /* Fallback: single-delete path for the first item only. */
    const first = items[0];
    if (first && onDeleteThread) onDeleteThread(first.id, first.title);
    clearSelection();
  }, [clearSelection, onDeleteThread, onDeleteThreads, selectedAlive, threads]);

  return (
    <div className={`chat-history${selecting ? ' is-selecting' : ''}`} data-zone="ZONE_BODY">
      <button
        type="button"
        className="chat-history__close icon-hover"
        aria-label={t('dialog.close')}
        title={t('dialog.close')}
        onClick={onClose}
      >
        <IconX size={18} />
      </button>

      <div className="chat-history__inner">
        <h1 className="chat-history__title">{t('historyPage.title')}</h1>

        <div className="chat-history__search">
          <IconSearch size={19} className="chat-history__search-icon" aria-hidden />
          <input
            type="search"
            className="chat-history__search-input"
            value={query}
            placeholder={t('historyPage.search')}
            aria-label={t('historyPage.search')}
            onChange={event => setQuery(event.target.value)}
          />
          {query ? (
            <button
              type="button"
              className="chat-history__search-clear icon-hover"
              aria-label={t('dialog.close')}
              onClick={() => setQuery('')}
            >
              <IconX size={14} />
            </button>
          ) : null}
        </div>

        {threads.length === 0 ? (
          <div className="chat-history__empty">
            <p className="chat-history__empty-title">{t('historyPage.empty')}</p>
            <p className="chat-history__empty-body">{t('historyPage.emptyBody')}</p>
            <button type="button" className="kimi-btn kimi-btn--primary" onClick={onNewChat}>
              {t('historyPage.newChat')}
            </button>
          </div>
        ) : total === 0 ? (
          <div className="chat-history__no-results" role="status">
            <HistoryEmptySearchArt />
            <p className="chat-history__no-results-text">{t('historyPage.noResults')}</p>
          </div>
        ) : (
          groups.map(group => (
            <section
              key={group.id}
              className="chat-history__group"
              aria-label={t(GROUP_LABEL[group.id])}
            >
              <h2 className="chat-history__group-title">{t(GROUP_LABEL[group.id])}</h2>
              <ul className="chat-history__list">
                {group.items.map(thread => {
                  const title = thread.title.trim() || t('sidebar.untitled');
                  const preview = previews[thread.id];
                  return (
                    <HistoryChatRow
                      key={thread.id}
                      thread={thread}
                      title={title}
                      active={thread.id === activeThreadId}
                      pinned={pinnedThreadIds.includes(thread.id)}
                      selected={selectedAlive.has(thread.id)}
                      selecting={selecting}
                      meta={metaLabel(thread.updatedAt, now)}
                      snippet={preview?.snippet ?? thread.snippet ?? null}
                      files={preview?.files ?? thread.files ?? []}
                      onOpen={() => onOpenThread(thread.id)}
                      onToggleSelected={() => toggleSelected(thread.id)}
                      onRename={onRenameThread ? () => onRenameThread(thread.id) : undefined}
                      onPin={onPinThread ? () => onPinThread(thread.id) : undefined}
                      onDelete={onDeleteThread ? () => onDeleteThread(thread.id, title) : undefined}
                    />
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>

      {selecting ? (
        <div className="chat-history__bulk" role="toolbar" aria-label={t('historyPage.bulkBar')}>
          <button type="button" className="chat-history__bulk-exit" onClick={clearSelection}>
            <IconChevronLeft size={16} />
            <span>{t('historyPage.bulkExit')}</span>
          </button>
          <span className="chat-history__bulk-count">
            {t('historyPage.bulkSelected', { count: selectedAlive.size })}
          </span>
          <button type="button" className="chat-history__bulk-delete" onClick={requestBulkDelete}>
            <span>{t('historyPage.bulkDelete')}</span>
            <IconTrash size={16} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
