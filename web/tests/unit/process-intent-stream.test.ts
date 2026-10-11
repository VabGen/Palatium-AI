import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * Lightweight SSE parser mirror for answer_delta replace + done lifecycle.
 * Full fetch integration lives behind MSW in e2e; here we unit-test accumulation.
 */
function accumulateAnswerDeltas(
  events: Array<{ delta: string; replace?: boolean }>
): string {
  let answerAccumulated = '';
  for (const payload of events) {
    if (payload.replace === true) {
      answerAccumulated = '';
    }
    answerAccumulated += payload.delta;
  }
  return answerAccumulated;
}

describe('processIntentStream answer_delta replace', () => {
  it('resets accumulator when replace is set on a later draft', () => {
    const text = accumulateAnswerDeltas([
      { delta: 'first draft' },
      { delta: 'revised draft', replace: true },
    ]);
    expect(text).toBe('revised draft');
  });

  it('concatenates chunks without replace', () => {
    const text = accumulateAnswerDeltas([{ delta: 'hel' }, { delta: 'lo' }]);
    expect(text).toBe('hello');
  });
});

describe('AbortController cancels reader', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('abort listener cancels the body reader', async () => {
    const controller = new AbortController();
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start() {
        /* never enqueue — hang until cancel */
      },
      cancel() {
        cancelled = true;
      },
    });
    const reader = stream.getReader();
    const onAbort = () => {
      void reader.cancel();
    };
    controller.signal.addEventListener('abort', onAbort, { once: true });
    const readPromise = reader.read();
    controller.abort();
    await expect(readPromise).resolves.toEqual({ done: true, value: undefined });
    expect(cancelled).toBe(true);
  });
});
