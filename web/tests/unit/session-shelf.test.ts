import { describe, expect, it } from 'vitest';
import {
  groupShelfByProject,
  mapSessionsToShelf,
  mergeShelfWithLiveThread,
} from '../../src/lib/sessionShelf';

describe('P1b session shelf mapping', () => {
  it('maps durable sessions and skips empty/duplicate thread ids', () => {
    expect(
      mapSessionsToShelf(
        [
          { thread_id: 't1', title: 'Alpha', project_id: 'p1' },
          { thread_id: 't1', title: 'dup' },
          { thread_id: '  ', title: 'x' },
          { thread_id: 't2', title: null },
        ],
        'Untitled'
      )
    ).toEqual([
      { id: 't1', title: 'Alpha', projectId: 'p1' },
      { id: 't2', title: 'Untitled', projectId: null },
    ]);
  });

  it('keeps live thread first and preserves a durable shelf title', () => {
    expect(
      mergeShelfWithLiveThread(
        [
          { id: 'old', title: 'Yesterday', projectId: null },
          { id: 'live', title: 'Renamed by user', projectId: 'p1' },
        ],
        'live',
        'first user message…',
        'p1'
      )
    ).toEqual([
      { id: 'live', title: 'Renamed by user', projectId: 'p1' },
      { id: 'old', title: 'Yesterday', projectId: null },
    ]);
  });

  it('seeds title from the live thread when the row is new or still untitled', () => {
    expect(
      mergeShelfWithLiveThread(
        [{ id: 'old', title: 'Yesterday', projectId: null }],
        'live',
        'Hello there',
        null
      )
    ).toEqual([
      { id: 'live', title: 'Hello there', projectId: null },
      { id: 'old', title: 'Yesterday', projectId: null },
    ]);

    expect(
      mergeShelfWithLiveThread(
        [{ id: 'live', title: 'Untitled', projectId: null }],
        'live',
        'Hello there',
        null,
        ['Untitled', 'New chat']
      )
    ).toEqual([{ id: 'live', title: 'Hello there', projectId: null }]);
  });
});

describe('A3 project shelf filter', () => {
  it('keeps only threads for the active project (plus live thread)', () => {
    const shelf = [
      { id: 't1', title: 'One', projectId: 'p1' },
      { id: 't2', title: 'Two', projectId: null },
      { id: 'live', title: 'Live', projectId: 'p2' },
    ];
    const filterId = 'p1';
    const filtered = shelf.filter(row => row.projectId === filterId || row.id === 'live');
    expect(filtered.map(r => r.id)).toEqual(['t1', 'live']);
  });
});

describe('P2 groupShelfByProject', () => {
  it('groups pinned threads under project titles and keeps unpinned last', () => {
    expect(
      groupShelfByProject(
        [
          { id: 't1', title: 'One', projectId: 'p1' },
          { id: 't2', title: 'Two', projectId: null },
          { id: 't3', title: 'Three', projectId: 'p1' },
          { id: 't4', title: 'Four', projectId: 'unknown' },
        ],
        [{ id: 'p1', title: 'Alpha' }]
      )
    ).toEqual([
      {
        projectId: 'p1',
        title: 'Alpha',
        threads: [
          { id: 't1', title: 'One', projectId: 'p1' },
          { id: 't3', title: 'Three', projectId: 'p1' },
        ],
      },
      {
        projectId: 'unknown',
        title: 'unknown',
        threads: [{ id: 't4', title: 'Four', projectId: 'unknown' }],
      },
      {
        projectId: null,
        title: '',
        threads: [{ id: 't2', title: 'Two', projectId: null }],
      },
    ]);
  });
});
