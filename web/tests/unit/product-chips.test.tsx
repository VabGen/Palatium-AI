import { act, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductChips } from '../../src/components/ProductChips';
import { setI18nLocale } from '../../src/i18n';

const CHIPS = [
  { id: 'make3d', label: '3D Make', icon: <span /> },
  { id: 'slides', label: 'Slides', icon: <span /> },
  { id: 'build', label: 'Build', icon: <span /> },
];

/**
 * jsdom has no layout, so the rail geometry is stubbed. `scrollBy` deliberately
 * does NOT dispatch a `scroll` event: that is exactly the webview case where the
 * reverse carousel arrow used to stay hidden after clicking the trailing one.
 */
function stubRail(container: HTMLElement) {
  const track = container.querySelector('.product-chips__track') as HTMLDivElement;
  let left = 0;

  Object.defineProperty(track, 'scrollWidth', { value: 600, configurable: true });
  Object.defineProperty(track, 'clientWidth', { value: 300, configurable: true });
  Object.defineProperty(track, 'scrollLeft', {
    configurable: true,
    get: () => left,
    set: value => {
      left = value;
    },
  });

  track.scrollBy = ((options: ScrollToOptions) => {
    left = Math.min(300, Math.max(0, left + (options.left ?? 0)));
  }) as typeof track.scrollBy;

  return { track, readLeft: () => left };
}

beforeEach(() => {
  setI18nLocale('en-US');
  vi.useFakeTimers();
  // jsdom schedules animation frames outside the fake clock, so the measurement
  // would never run inside `advanceTimersByTime`. Bind frames to fake timers.
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) =>
    window.setTimeout(() => cb(performance.now()), 16)
  );
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setI18nLocale('ru-RU');
});

describe('Product chips carousel', () => {
  const advance = (ms: number) => {
    act(() => {
      vi.advanceTimersByTime(ms);
    });
  };

  it('shows the trailing arrow only while the rail has more to reveal', () => {
    const { container } = render(<ProductChips chips={CHIPS} onSelect={vi.fn()} />);
    stubRail(container);
    advance(50);

    expect(container.querySelector('.product-chips__arrow--next')).not.toBeNull();
    expect(container.querySelector('.product-chips__arrow--prev')).toBeNull();
  });

  it('reveals the reverse arrow after the trailing arrow scrolls the rail', () => {
    const { container } = render(<ProductChips chips={CHIPS} onSelect={vi.fn()} />);
    const { readLeft } = stubRail(container);
    advance(50);

    fireEvent.click(container.querySelector('.product-chips__arrow--next') as HTMLElement);
    advance(800);

    expect(readLeft()).toBeGreaterThan(0);
    expect(container.querySelector('.product-chips__arrow--prev')).not.toBeNull();
    expect(container.querySelector('.product-chips__arrow--next')).not.toBeNull();

    fireEvent.click(container.querySelector('.product-chips__arrow--next') as HTMLElement);
    advance(800);

    expect(readLeft()).toBe(300);
    expect(container.querySelector('.product-chips__arrow--prev')).not.toBeNull();
    expect(container.querySelector('.product-chips__arrow--next')).toBeNull();

    fireEvent.click(container.querySelector('.product-chips__arrow--prev') as HTMLElement);
    advance(800);

    expect(readLeft()).toBe(140);
    expect(container.querySelector('.product-chips__arrow--prev')).not.toBeNull();

    fireEvent.click(container.querySelector('.product-chips__arrow--prev') as HTMLElement);
    advance(800);

    expect(readLeft()).toBe(0);
    expect(container.querySelector('.product-chips__arrow--prev')).toBeNull();
    expect(container.querySelector('.product-chips__arrow--next')).not.toBeNull();
  });
});
