import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type RefObject,
} from 'react';
import { AttachmentFileIcon } from '../icons/fileTypeIcons';
import {
  dialogueTurnDomId,
  type DialogueNavEntry,
} from '../lib/dialogueNav';
import { t } from '../i18n';

type DialogueNavProps = {
  entries: readonly DialogueNavEntry[];
  scrollRootRef: RefObject<HTMLElement | null>;
  onJump?: (id: string) => void;
};

/**
 * Kimi ``conversation-turn-navigator`` interaction (DevTools 2026-11-11):
 * - Collapsed: only ``__trigger`` ticks (pitch 32px, margin 15.25).
 * - Expanded: trigger ``opacity:0`` in place; ``__panel`` at ``left:0`` overlays so
 *   panel ticks share the **same** client rects (Δx=Δy=0). Tick only grows 8→10.
 * Nothing relocates — the window forms around the stick.
 */
export function DialogueNav({ entries, scrollRootRef, onJump }: DialogueNavProps) {
  const [activeId, setActiveId] = useState(() => entries[entries.length - 1]?.id ?? '');
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const lockRef = useRef<string | null>(null);

  useEffect(() => {
    if (entries.length === 0) return;
    if (!entries.some(entry => entry.id === activeId)) {
      setActiveId(entries[entries.length - 1]?.id ?? '');
    }
  }, [entries, activeId]);

  useEffect(() => {
    const root = scrollRootRef.current;
    if (!root || entries.length === 0) return;
    const nodes = entries
      .map(entry => root.querySelector<HTMLElement>(`#${CSS.escape(dialogueTurnDomId(entry.id))}`))
      .filter((node): node is HTMLElement => node != null);
    if (nodes.length === 0) return;

    const visible = new Map<string, IntersectionObserverEntry>();
    if (typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(
      records => {
        if (lockRef.current) return;
        for (const record of records) {
          const id = (record.target as HTMLElement).dataset.turnId;
          if (!id) continue;
          if (record.isIntersecting) visible.set(id, record);
          else visible.delete(id);
        }
        if (visible.size === 0) return;
        let bestId = '';
        let bestTop = Number.POSITIVE_INFINITY;
        for (const [id, entry] of visible) {
          const top = entry.boundingClientRect.top;
          if (top < bestTop) {
            bestTop = top;
            bestId = id;
          }
        }
        if (bestId) setActiveId(bestId);
      },
      { root, rootMargin: '-10% 0px -55% 0px', threshold: [0, 0.01, 0.1] }
    );
    for (const node of nodes) observer.observe(node);
    return () => observer.disconnect();
  }, [entries, scrollRootRef]);

  const jumpTo = useCallback(
    (id: string) => {
      lockRef.current = id;
      setActiveId(id);
      const root = scrollRootRef.current;
      root
        ?.querySelector<HTMLElement>(`#${CSS.escape(dialogueTurnDomId(id))}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      onJump?.(id);
      window.setTimeout(() => {
        lockRef.current = null;
      }, 700);
    },
    [onJump, scrollRootRef]
  );

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const index = entries.findIndex(entry => entry.id === activeId);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const next = entries[Math.min(entries.length - 1, Math.max(0, index) + 1)];
      if (next) jumpTo(next.id);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      const prev = entries[Math.max(0, index - 1)];
      if (prev) jumpTo(prev.id);
    }
  };

  if (entries.length === 0) return null;

  const countStyle = {
    ['--visible-turn-count']: String(entries.length),
  } as CSSProperties;

  return (
    <nav
      className="dialogue-nav"
      aria-label={t('a11y.dialogueNav')}
      style={countStyle}
      onKeyDown={onKeyDown}
    >
      {/* Collapsed stick — same pixel column as panel ticks when expanded. */}
      <button
        type="button"
        className="dialogue-nav__trigger"
        aria-label={t('a11y.dialogueNav')}
        aria-expanded={false}
        tabIndex={0}
      >
        <span className="dialogue-nav__ticks" aria-hidden>
          {entries.map(entry => (
            <span
              key={entry.id}
              className={`dialogue-nav__tick${entry.id === activeId ? ' is-active' : ''}`}
            />
          ))}
        </span>
      </button>

      {/* Panel overlays left:0 — ticks stay put (Δx=Δy=0 vs trigger). */}
      <div className="dialogue-nav__panel">
        <ul className="dialogue-nav__list">
          {entries.map(entry => {
            const active = entry.id === activeId;
            const highlighted = entry.id === highlightedId;
            return (
              <li key={entry.id} className="dialogue-nav__row">
                <button
                  type="button"
                  className={[
                    'dialogue-nav__item',
                    active ? 'is-active' : '',
                    highlighted ? 'is-highlighted' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  aria-label={entry.label}
                  data-name-tip={entry.label}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => jumpTo(entry.id)}
                  onMouseEnter={() => setHighlightedId(entry.id)}
                  onMouseLeave={() => setHighlightedId(null)}
                  onFocus={() => setHighlightedId(entry.id)}
                  onBlur={() => setHighlightedId(null)}
                >
                  {entry.hasFile && entry.fileName ? (
                    <span className="dialogue-nav__file">
                      <AttachmentFileIcon kind={entry.iconKind} size={18} />
                      <span className="dialogue-nav__file-name">{entry.fileName}</span>
                      {entry.extraCount > 0 ? (
                        <span className="dialogue-nav__count">+{entry.extraCount}</span>
                      ) : null}
                    </span>
                  ) : null}
                  {entry.prompt ? (
                    <span className="dialogue-nav__prompt">{entry.prompt}</span>
                  ) : null}
                </button>
                <span className="dialogue-nav__tick-slot" aria-hidden>
                  <span
                    className={`dialogue-nav__tick${active ? ' is-active' : ''}`}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
