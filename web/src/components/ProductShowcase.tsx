import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { t } from '../i18n';
import { IconGlyphChevronLeft, IconGlyphRemix } from '../icons/kimiGlyphs';
import {
  PRODUCT_SHOWCASES,
  type ProductShowcaseData,
  type ShowcaseCard,
} from '../mocks/productShowcases';
import type { ShellView } from '../lib/shellView';
import { showcaseThumbStyle } from '../lib/showcase';

export type ProductShowcaseProps = {
  view: ShellView;
  /** Insert example prompt into the composer — no detail overlay / navigation. */
  onSelectPrompt?: (prompt: string) => void;
};

/** Rotate by one so «Shuffle» reorders the shelf without losing cards. */
function rotate<T>(items: readonly T[], by: number): readonly T[] {
  if (items.length === 0) return items;
  const offset = by % items.length;
  return [...items.slice(offset), ...items.slice(0, offset)];
}

function cardCaption(card: ShowcaseCard): string {
  return card.title;
}

/**
 * Product shelves under the composer. Card click only fills the chat prompt.
 */
export function ProductShowcase({
  view,
  onSelectPrompt,
}: ProductShowcaseProps): ReactElement | null {
  const data: ProductShowcaseData | undefined = PRODUCT_SHOWCASES[view];
  const [activeTab, setActiveTab] = useState(data?.tabs?.[0]?.id ?? '');
  const [shuffleBy, setShuffleBy] = useState(0);
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const [canScroll, setCanScroll] = useState({ start: false, end: false });

  const activeTabId = data?.tabs?.some(tab => tab.id === activeTab)
    ? activeTab
    : (data?.tabs?.[0]?.id ?? '');

  const cards = useMemo(() => {
    if (!data) return [];
    const isAllTab = !data.tabs || data.tabs[0]?.id === activeTabId;
    const filtered = isAllTab
      ? data.cards
      : data.cards.filter(card => card.tabs?.includes(activeTabId));
    return data.masonry ? filtered : rotate(filtered, shuffleBy);
  }, [activeTabId, data, shuffleBy]);

  const syncScroll = useCallback(() => {
    const el = tabsRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const start = el.scrollLeft > 1;
    const end = el.scrollLeft < max - 1;
    setCanScroll(previous =>
      previous.start === start && previous.end === end ? previous : { start, end }
    );
  }, []);

  useEffect(() => {
    const el = tabsRef.current;
    if (!el) return;
    const frame = requestAnimationFrame(syncScroll);
    el.addEventListener('scroll', syncScroll, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(syncScroll);
    observer?.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener('scroll', syncScroll);
      observer?.disconnect();
    };
  }, [data, syncScroll]);

  const scrollTabs = useCallback((direction: -1 | 1) => {
    const el = tabsRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * Math.max(160, el.clientWidth * 0.8), behavior: 'smooth' });
  }, []);

  if (!data) return null;

  const masonry = data.masonry === true;
  const promptFor = (card: ShowcaseCard) => t('showcase.prompt', { title: card.title });

  return (
    <section
      className={`product-showcase${masonry ? ' product-showcase--masonry' : ''}`}
      aria-label={data.heading ?? data.tabs?.[0]?.label ?? t('empty.suggestionsLabel')}
    >
      {data.tabs ? (
        <div className="product-showcase__tabs-wrap">
          <div
            ref={tabsRef}
            className="product-showcase__tabs"
            role="tablist"
            aria-label={data.heading ?? 'Templates'}
          >
            {data.tabs.map(tab => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={tab.id === activeTabId}
                className={`product-showcase__tab${tab.id === activeTabId ? ' is-selected' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {canScroll.start ? (
            <button
              type="button"
              className="product-showcase__nav"
              aria-label={t('showcase.prevCategories')}
              onClick={() => scrollTabs(-1)}
            >
              <span className="product-showcase__nav-arrow" aria-hidden>
                <IconGlyphChevronLeft size={20} />
              </span>
            </button>
          ) : null}
          {canScroll.end ? (
            <button
              type="button"
              className="product-showcase__nav is-next"
              aria-label={t('showcase.nextCategories')}
              onClick={() => scrollTabs(1)}
            >
              <span className="product-showcase__nav-arrow" aria-hidden>
                <IconGlyphChevronLeft size={20} />
              </span>
            </button>
          ) : null}
        </div>
      ) : (
        <div className="product-showcase__header">
          <span className="product-showcase__title">{data.heading}</span>
          {data.action === 'shuffle' ? (
            <button
              type="button"
              className="product-showcase__action icon-hover"
              onClick={() => setShuffleBy(value => value + 1)}
            >
              <span>{t('showcase.shuffle')}</span>
            </button>
          ) : null}
        </div>
      )}

      <ul className="product-showcase__grid" key={activeTabId}>
        {cards.map(card => (
          <li key={card.id} className="product-showcase__item">
            <button
              type="button"
              className="product-showcase__card icon-hover"
              onClick={() => onSelectPrompt?.(promptFor(card))}
              aria-label={t('showcase.insertAria', { title: cardCaption(card) })}
            >
              <span className="product-showcase__media" data-tall={card.tall ? 'true' : undefined}>
                <span
                  className="product-showcase__thumb"
                  style={showcaseThumbStyle(card)}
                  aria-hidden
                />
                {masonry ? (
                  <>
                    <span className="product-showcase__mask" aria-hidden />
                    <span className="product-showcase__actions" aria-hidden>
                      <span className="product-showcase__remix">
                        <IconGlyphRemix size={18} />
                        <span>{t('inspiration.remix')}</span>
                      </span>
                    </span>
                  </>
                ) : null}
              </span>
              {masonry ? null : (
                <span className="product-showcase__caption">{cardCaption(card)}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
