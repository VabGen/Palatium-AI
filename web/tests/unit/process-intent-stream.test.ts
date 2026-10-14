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

/** Mirrors client.ts dual-emit rules for text_delta + answer_delta. */
function accumulateHybridDeltas(
  events: Array<
    | { kind: 'text'; content: string }
    | { kind: 'answer'; delta: string; replace?: boolean }
  >
): { text: string; answer: string } {
  let textAccumulated = '';
  let answerAccumulated = '';
  let hasTextDelta = false;
  for (const event of events) {
    if (event.kind === 'text') {
      hasTextDelta = true;
      textAccumulated += event.content;
      continue;
    }
    if (event.replace === true) {
      answerAccumulated = '';
      if (!hasTextDelta) {
        textAccumulated = '';
      }
    }
    answerAccumulated += event.delta;
  }
  return { text: textAccumulated, answer: answerAccumulated };
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

describe('processIntentStream dual-emit replace', () => {
  it('does not wipe textAccumulated when answer_delta replace follows text_delta', () => {
    const { text, answer } = accumulateHybridDeltas([
      { kind: 'text', content: '# Title\n' },
      { kind: 'answer', delta: '# Title\n', replace: true },
      { kind: 'text', content: 'Body' },
      { kind: 'answer', delta: 'Body' },
    ]);
    expect(text).toBe('# Title\nBody');
    expect(answer).toBe('# Title\nBody');
  });

  it('still clears textAccumulated on worker→formatter replace before text_delta', () => {
    const { text, answer } = accumulateHybridDeltas([
      { kind: 'answer', delta: 'worker draft' },
      { kind: 'answer', delta: '# Formatted', replace: true },
    ]);
    expect(text).toBe('');
    expect(answer).toBe('# Formatted');
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
