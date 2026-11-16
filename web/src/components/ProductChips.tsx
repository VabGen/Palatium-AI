import { useCallback, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react';
import { IconGlyphChevronLeft } from '../icons/kimiGlyphs';
import { t } from '../i18n';

export type ProductChipItem = {
  id: string;
  label: string;
  icon: ReactNode;
};

type ProductChipsProps = {
  chips: readonly ProductChipItem[];
  onSelect: (id: string) => void;
};

type ScrollEdges = { start: boolean; end: boolean };

/**
 * Kimi home publisher shortcuts — one 36px line of pills. Arrows are only
 * chrome for overflow: the leading chevron appears once the line is scrolled
 * (so the reverse direction is always reachable), the trailing one hides when
 * the shelf is fully revealed — same rule as `ProductShowcase` tabs.
 */
export function ProductChips({ chips, onSelect }: ProductChipsProps): ReactElement {
  const trackRef = useRef<HTMLDivElement>(null);
  const watchRef = useRef<number | null>(null);
  const timeoutRef = useRef<number[]>([]);
  const [edges, setEdges] = useState<ScrollEdges>({ start: false, end: false });

  const sync = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const start = el.scrollLeft > 1;
    const end = max > 1 && el.scrollLeft < max - 1;
    setEdges(previous =>
      previous.start === start && previous.end === end ? previous : { start, end }
    );
  }, []);

  /**
   * Programmatic smooth scrolls do not reliably emit `scroll` in every webview,
   * which used to leave the reverse arrow hidden. Poll on rAF until the rail
   * settles, with timer ticks as a fallback for throttled frames.
   */
  const watchScroll = useCallback(() => {
    if (watchRef.current !== null) cancelAnimationFrame(watchRef.current);
    const startedAt = performance.now();
    const step = () => {
      sync();
      watchRef.current = performance.now() - startedAt < 700 ? requestAnimationFrame(step) : null;
    };
    watchRef.current = requestAnimationFrame(step);
    if (timeoutRef.current.length) timeoutRef.current.forEach(clearTimeout);
    timeoutRef.current = [120, 320, 600].map(delay => window.setTimeout(sync, delay));
  }, [sync]);

  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;

    /* Defer the first measurement out of the effect body (no sync setState). */
    const frame = requestAnimationFrame(sync);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(sync);
    observer?.observe(el);
    el.addEventListener('scroll', sync, { passive: true });
    window.addEventListener('resize', sync);
    return () => {
      cancelAnimationFrame(frame);
      if (watchRef.current !== null) cancelAnimationFrame(watchRef.current);
      timeoutRef.current.forEach(clearTimeout);
      timeoutRef.current = [];
      observer?.disconnect();
      el.removeEventListener('scroll', sync);
      window.removeEventListener('resize', sync);
    };
  }, [chips, sync]);

  const scrollBy = (direction: -1 | 1) => {
    const el = trackRef.current;
    if (!el) return;
    el.scrollBy({ left: direction * Math.max(160, el.clientWidth * 0.45), behavior: 'smooth' });
    watchScroll();
  };

  return (
    <div className="product-chips" role="group" aria-label={t('empty.suggestionsLabel')}>
      <div className="product-chips__track" ref={trackRef}>
        {chips.map(chip => (
          <button
            key={chip.id}
            type="button"
            className="product-chip icon-hover"
            onClick={() => onSelect(chip.id)}
          >
            <span className="product-chip__icon">{chip.icon}</span>
            <span>{chip.label}</span>
          </button>
        ))}
      </div>
      {edges.start ? (
        <button
          type="button"
          className="product-chips__arrow product-chips__arrow--prev"
          aria-label={t('showcase.prevCategories')}
          onClick={() => scrollBy(-1)}
        >
          <span className="product-chips__arrow-btn">
            <IconGlyphChevronLeft size={20} />
          </span>
        </button>
      ) : null}
      {edges.end ? (
        <button
          type="button"
          className="product-chips__arrow product-chips__arrow--next"
          aria-label={t('empty.chipsScroll')}
          onClick={() => scrollBy(1)}
        >
          <span className="product-chips__arrow-btn">
            <IconGlyphChevronLeft size={20} />
          </span>
        </button>
      ) : null}
    </div>
  );
}
