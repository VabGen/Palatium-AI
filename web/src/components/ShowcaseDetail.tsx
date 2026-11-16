import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import { t } from '../i18n';
import { IconGlyphClose } from '../icons/kimiGlyphs';
import { showcaseThumbStyle } from '../lib/showcase';
import type { ShowcaseCard } from '../mocks/productShowcases';
import type { ShellView } from '../lib/shellView';
import { Avatar } from './ui/Avatar';

export type ShowcaseDetailProps = {
  card: ShowcaseCard;
  view: ShellView;
  prompt: string;
  onClose: () => void;
  onRemix: (prompt: string) => void;
};

/** Shareable deep link for an inspiration card (`#/make3d?item=<id>`). */
function cardLink(view: ShellView, card: ShowcaseCard): string {
  return `${window.location.origin}${window.location.pathname}${window.location.search}#/${view}?item=${encodeURIComponent(card.id)}`;
}

/**
 * kimi.ai `inspiration-detail` modal: 910×788 sheet (preview + 320px panel),
 * mask 50% black, panel radius 16, 0 8px 32px shadow.
 */
export function ShowcaseDetail({
  card,
  view,
  prompt,
  onClose,
  onRemix,
}: ShowcaseDetailProps): ReactElement {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const restoreRef = useRef<Element | null>(null);
  const copyTimerRef = useRef<number | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    restoreRef.current = typeof document === 'undefined' ? null : document.activeElement;
    closeRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
      if (restoreRef.current instanceof HTMLElement) restoreRef.current.focus();
    };
  }, [onClose]);

  const handleCopy = useCallback(() => {
    const write = navigator.clipboard?.writeText(cardLink(view, card));
    if (!write) return;
    void write
      .then(() => {
        setCopied(true);
        if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
        copyTimerRef.current = window.setTimeout(() => setCopied(false), 1600);
      })
      .catch(() => undefined);
  }, [card, view]);

  return (
    <div
      className="showcase-detail"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="showcase-detail__sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="showcase-detail-title"
      >
        <div className="showcase-detail__preview" style={showcaseThumbStyle(card)} aria-hidden />
        <div className="showcase-detail__panel">
          <header className="showcase-detail__header">
            <h2 className="showcase-detail__title" id="showcase-detail-title">
              {card.title}
            </h2>
            <button
              ref={closeRef}
              type="button"
              className="showcase-detail__close"
              aria-label={t('showcase.close')}
              onClick={onClose}
            >
              <IconGlyphClose size={18} />
            </button>
          </header>
          <div className="showcase-detail__scroll">
            <p className="showcase-detail__copy">{prompt}</p>
            <div className="showcase-detail__author">
              <Avatar kind="assistant" size={20} />
              <span>{t('showcase.selectedBy')}</span>
            </div>
          </div>
          <div className="showcase-detail__actions">
            <button type="button" className="showcase-detail__action" onClick={handleCopy}>
              {copied ? t('showcase.copied') : t('showcase.copyLink')}
            </button>
            <button
              type="button"
              className="showcase-detail__action is-primary"
              onClick={() => onRemix(prompt)}
            >
              {t('inspiration.remix')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
