/**
 * TTFVF: измерение «первого видимого кадра» (W1-клиент, 084).
 *
 * Проверяется то, что легко испортить незаметно:
 *  - старт снимается СИНХРОННО (до await), иначе метрика впитывает сеть;
 *  - замер ждёт именно второй кадр (после paint), а не первый (до paint);
 *  - бюджет — одна константа, общая с E2E-гейтом;
 *  - запись в таймлайн не растёт без предела и её падение не ломает turn.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  MAX_TTFVF_MEASURES,
  TTFVF_BUDGET_MS,
  TTFVF_MEASURE,
  afterNextPaint,
  markFirstVisualStart,
  measureFirstVisual,
} from '../../src/lib/firstVisual';

/** Прогон «после кадра» без ожидания: тест не зависит от rAF-таймеров jsdom. */
const immediate = (run: () => void): void => run();

type MeasureGlobal = {
  measure: unknown;
  getEntriesByName: unknown;
  clearMeasures: unknown;
};

/** Подменить User Timing API на управляемый и вернуть исходные значения. */
function stubUserTiming(overrides: Partial<MeasureGlobal>): () => void {
  const original: MeasureGlobal = {
    measure: performance.measure,
    getEntriesByName: performance.getEntriesByName,
    clearMeasures: performance.clearMeasures,
  };
  for (const [key, value] of Object.entries(overrides)) {
    Object.defineProperty(performance, key, { value, configurable: true, writable: true });
  }
  return () => {
    for (const [key, value] of Object.entries(original)) {
      Object.defineProperty(performance, key, { value, configurable: true, writable: true });
    }
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('markFirstVisualStart', () => {
  it('returns the clock reading synchronously (no measurement side effects)', () => {
    expect(markFirstVisualStart(() => 12.5)).toBe(12.5);
  });
});

describe('measureFirstVisual', () => {
  it('measures submit → paint and reports the budget verdict', async () => {
    const sample = await measureFirstVisual(100, {
      now: () => 220,
      afterPaint: immediate,
    });

    expect(sample).toEqual({ durationMs: 120, withinBudget: true });
  });

  it('flags a sample over budget without throwing or retrying', async () => {
    const sample = await measureFirstVisual(0, {
      now: () => TTFVF_BUDGET_MS + 1,
      afterPaint: immediate,
    });

    expect(sample.withinBudget).toBe(false);
    expect(sample.durationMs).toBe(TTFVF_BUDGET_MS + 1);
  });

  it('never reports negative time if the clock is not monotonic', async () => {
    const sample = await measureFirstVisual(500, { now: () => 400, afterPaint: immediate });
    expect(sample.durationMs).toBe(0);
  });

  it('waits for the callback: the promise does not settle before the frame', async () => {
    const frames: Array<() => void> = [];
    const pending = measureFirstVisual(0, {
      now: () => 50,
      afterPaint: run => {
        frames.push(run);
      },
    });

    const settled = vi.fn();
    void pending.then(settled);
    await Promise.resolve();
    expect(settled).not.toHaveBeenCalled();

    expect(frames).toHaveLength(1);
    frames[0]?.();
    await expect(pending).resolves.toEqual({ durationMs: 50, withinBudget: true });
  });

  it('records the measurement in the performance timeline with the budget detail', async () => {
    const measure = vi.fn();
    const restore = stubUserTiming({
      measure,
      getEntriesByName: () => [],
      clearMeasures: vi.fn(),
    });

    try {
      await measureFirstVisual(10, { now: () => 40, afterPaint: immediate });
    } finally {
      restore();
    }

    expect(measure).toHaveBeenCalledWith(TTFVF_MEASURE, {
      start: 10,
      end: 40,
      detail: { budgetMs: TTFVF_BUDGET_MS },
    });
  });

  it('clears the timeline before it can grow past the cap', async () => {
    const measure = vi.fn();
    const clearMeasures = vi.fn();
    const restore = stubUserTiming({
      measure,
      getEntriesByName: () => Array.from({ length: MAX_TTFVF_MEASURES }, () => ({})),
      clearMeasures,
    });

    try {
      await measureFirstVisual(0, { now: () => 5, afterPaint: immediate });
    } finally {
      restore();
    }

    expect(clearMeasures).toHaveBeenCalledWith(TTFVF_MEASURE);
    expect(measure).toHaveBeenCalledTimes(1);
  });

  it('resolves the sample even when the timeline API refuses the write', async () => {
    const restore = stubUserTiming({
      measure: () => {
        throw new TypeError('unsupported measure signature');
      },
      getEntriesByName: () => [],
      clearMeasures: vi.fn(),
    });

    try {
      await expect(
        measureFirstVisual(0, { now: () => 30, afterPaint: immediate })
      ).resolves.toEqual({ durationMs: 30, withinBudget: true });
    } finally {
      restore();
    }
  });

  it('resolves the sample when the User Timing API is absent entirely', async () => {
    const restore = stubUserTiming({
      measure: undefined,
      getEntriesByName: undefined,
      clearMeasures: undefined,
    });

    try {
      // `performance.measure` не функция: вызов упадёт и будет подавлен внутри.
      await expect(measureFirstVisual(0, { now: () => 7, afterPaint: immediate })).resolves.toEqual(
        { durationMs: 7, withinBudget: true }
      );
    } finally {
      restore();
    }
  });
});

describe('afterNextPaint', () => {
  it('runs after the SECOND frame, not the first', () => {
    const run = vi.fn();
    const callbacks: FrameRequestCallback[] = [];
    const stub = (callback: FrameRequestCallback): number => {
      callbacks.push(callback);
      return callbacks.length;
    };
    vi.stubGlobal('requestAnimationFrame', stub);

    try {
      afterNextPaint(run);

      // Первый кадр ещё не означает отрисовку: здесь только commit + layout.
      expect(callbacks).toHaveLength(1);
      callbacks[0](0);
      expect(run).not.toHaveBeenCalled();

      // Второй колбэк — уже после paint.
      expect(callbacks).toHaveLength(2);
      callbacks[1](0);
      expect(run).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('falls back to a microtask where frames do not exist (jsdom, old engines)', async () => {
    vi.stubGlobal('requestAnimationFrame', undefined);
    try {
      const run = vi.fn();
      afterNextPaint(run);
      expect(run).not.toHaveBeenCalled();
      await Promise.resolve();
      expect(run).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
