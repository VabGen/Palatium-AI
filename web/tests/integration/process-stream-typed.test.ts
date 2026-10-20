import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';

import { processIntentStream } from '../../src/api/client';
import { setAuthToken, setRuntimeMode } from '../../src/runtime/auth';
import type { ContentBlock, FormatterTaskResult } from '../../src/types/contentDocument';
import { server } from '../msw';

/**
 * Typed structured preview (wave 2): the SSE parser must hand closed document
 * blocks to the client untouched, before the final ``result`` arrives — that is
 * what lets ``BlockRenderer`` paint the answer instead of a Markdown mirror.
 */

const RESULT: FormatterTaskResult = {
  task_id: 'task-1',
  agent_role: 'formatter',
  status: 'success',
  confidence: 0.9,
  requires_review: false,
  error: null,
  output: null,
  hitl_cards: [],
};

function sse(events: Array<{ event: string; data: unknown }>): string {
  return events
    .map(item => `event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`)
    .join('');
}

const PROCESS_URL = '*/api/intents/process/stream';

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken('tok-1');
});

describe('processIntentStream typed frames', () => {
  it('forwards document_title and typed block_delta frames in order', async () => {
    const body = sse([
      { event: 'document_title', data: { title: 'Сравнение файлов' } },
      {
        event: 'block_delta',
        data: { index: 0, block: { type: 'heading', level: 2, text: 'Отличия' } },
      },
      { event: 'answer_delta', data: { delta: 'Отличия' } },
      {
        event: 'block_delta',
        data: {
          index: 1,
          block: { type: 'table', columns: ['Поле', 'v1', 'v2'], rows: [['a', '1', '2']] },
        },
      },
      { event: 'result', data: { task_id: 'task-1', thread_id: 'th-1', result: RESULT } },
      { event: 'done', data: {} },
    ]);
    server.use(
      http.post(
        PROCESS_URL,
        () => new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
      )
    );

    const titles: string[] = [];
    const blocks: Array<{ index: number; block: ContentBlock }> = [];
    const result = await processIntentStream('сравни', 'th-1', null, null, [], {
      onDocumentTitle: title => titles.push(title),
      onBlockDelta: (index, block) => blocks.push({ index, block }),
    });

    expect(titles).toEqual(['Сравнение файлов']);
    expect(blocks.map(item => item.index)).toEqual([0, 1]);
    expect(blocks[1].block).toMatchObject({ type: 'table', columns: ['Поле', 'v1', 'v2'] });
    expect(result.task_id).toBe('task-1');
  });

  it('drops a malformed block frame instead of failing the turn', async () => {
    const body = sse([
      { event: 'block_delta', data: { index: 0, block: null } },
      { event: 'block_delta', data: { index: 1, block: { text: 'no type' } } },
      { event: 'result', data: { task_id: 'task-1', thread_id: 'th-1', result: RESULT } },
    ]);
    server.use(
      http.post(
        PROCESS_URL,
        () => new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
      )
    );

    const blocks: number[] = [];
    const result = await processIntentStream('сравни', 'th-1', null, null, [], {
      onBlockDelta: index => blocks.push(index),
    });

    expect(blocks).toEqual([]);
    // The final result still resolves: a preview defect is not a turn failure.
    expect(result.task_id).toBe('task-1');
  });
});
