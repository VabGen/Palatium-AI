import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { requestMemoryClear } from '../../src/api/client';
import { setAuthToken, setRuntimeMode } from '../../src/runtime/auth';
import { server } from '../msw';

const CLEAR_URL = '*/api/memory/clear';

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken('tok-1');
});

describe('requestMemoryClear', () => {
  it('sends DELETE with thread_id and returns the HITL card', async () => {
    let method = '';
    let body: Record<string, unknown> | null = null;
    server.use(
      http.delete(CLEAR_URL, async ({ request }) => {
        method = request.method;
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          card_id: 'card-clear-1',
          thread_id: 'th-clear',
          task_id: 'mem-clear-abc',
          purpose: 'mcp_tool_approval',
          title: 'clear_memory',
          options: [],
          risk_score: 0.85,
          status: 'pending',
          created_at: '2026-11-12T00:00:00Z',
          expires_at: '2026-11-12T00:05:00Z',
        });
      })
    );

    const card = await requestMemoryClear({ thread_id: 'th-clear' }, 'user-1', 'org-1');
    expect(method).toBe('DELETE');
    expect(body).toEqual({ thread_id: 'th-clear' });
    expect(card.task_id).toBe('mem-clear-abc');
  });
});
