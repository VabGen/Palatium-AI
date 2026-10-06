import { describe, expect, it } from 'vitest';

import {
  MAX_ATTACHMENT_BYTES,
  UPLOAD_CHUNK_BYTES,
  planChunkRanges,
  shouldUseChunkedUpload,
} from '../../src/lib/attachments';

describe('chunked upload planning', () => {
  it('keeps single-PUT files at or below the part size', () => {
    expect(shouldUseChunkedUpload(UPLOAD_CHUNK_BYTES)).toBe(false);
    expect(shouldUseChunkedUpload(UPLOAD_CHUNK_BYTES + 1)).toBe(true);
    expect(planChunkRanges(UPLOAD_CHUNK_BYTES)).toEqual([
      { index: 0, start: 0, end: UPLOAD_CHUNK_BYTES },
    ]);
  });

  it('splits a multi-part payload into contiguous [start, end) ranges', () => {
    const size = UPLOAD_CHUNK_BYTES * 2 + 100;
    const ranges = planChunkRanges(size);
    expect(ranges).toEqual([
      { index: 0, start: 0, end: UPLOAD_CHUNK_BYTES },
      { index: 1, start: UPLOAD_CHUNK_BYTES, end: UPLOAD_CHUNK_BYTES * 2 },
      { index: 2, start: UPLOAD_CHUNK_BYTES * 2, end: size },
    ]);
    expect(ranges.reduce((sum, r) => sum + (r.end - r.start), 0)).toBe(size);
  });

  it('covers the attachment byte cap without exceeding part size', () => {
    const ranges = planChunkRanges(MAX_ATTACHMENT_BYTES);
    expect(ranges.length).toBe(Math.ceil(MAX_ATTACHMENT_BYTES / UPLOAD_CHUNK_BYTES));
    for (const range of ranges) {
      expect(range.end - range.start).toBeLessThanOrEqual(UPLOAD_CHUNK_BYTES);
      expect(range.end - range.start).toBeGreaterThan(0);
    }
    expect(ranges.at(-1)?.end).toBe(MAX_ATTACHMENT_BYTES);
  });

  it('returns no parts for empty or invalid sizes', () => {
    expect(planChunkRanges(0)).toEqual([]);
    expect(planChunkRanges(-1)).toEqual([]);
    expect(planChunkRanges(100, 0)).toEqual([]);
  });
});
