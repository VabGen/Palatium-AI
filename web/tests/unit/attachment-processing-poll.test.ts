import { describe, expect, it, vi } from 'vitest';

import type { AttachmentResponse } from '../../src/api/client';
import { pollAttachmentUntilSettled } from '../../src/lib/attachments';

function row(status: AttachmentResponse['status']): AttachmentResponse {
  return {
    attachment_id: '11111111-1111-1111-1111-111111111111',
    thread_id: 'thread-1',
    filename: 'scan.pdf',
    mime_type: 'application/pdf',
    size_bytes: 1024,
    mode: 'attach',
    status,
    page_count: null,
    rejection_reason: null,
    error: null,
    created_at: '2026-10-20T07:04:15Z',
    expires_at: null,
  };
}

/** Polling cadence is not part of the contract under test — no wall-clock waits. */
const noSleep = async (): Promise<void> => {};

describe('attachment processing poll', () => {
  it('polls until the pipeline reports a terminal status', async () => {
    const queue: AttachmentResponse['status'][] = ['pending', 'scanning', 'ready'];
    const read = vi.fn(async () => row(queue.shift() ?? 'ready'));

    const settled = await pollAttachmentUntilSettled(read, { sleep: noSleep });

    expect(settled.status).toBe('ready');
    expect(read).toHaveBeenCalledTimes(3);
  });

  it('returns a refused row instead of throwing — the reason belongs to the chip', async () => {
    const settled = await pollAttachmentUntilSettled(async () => row('rejected'), {
      sleep: noSleep,
    });

    expect(settled.status).toBe('rejected');
  });

  it('gives up after the attempt ceiling with a bounded, user-facing error', async () => {
    await expect(
      pollAttachmentUntilSettled(async () => row('scanning'), { limit: 2, sleep: noSleep })
    ).rejects.toThrow('обработка файла не завершилась');
  });
});
