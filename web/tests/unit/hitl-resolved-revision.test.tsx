/**
 * HITL-резолв (W7b): ответ на карточку приносит и документ, и diff.
 *
 * Что здесь зафиксировано, потому что ломается молча:
 *  - `revision` из ответа `/hitl/{id}/respond` доезжает до обработчика чата вместе с
 *    `resumed`, иначе после reject документ заменяется, а разметка появляется только
 *    после перезагрузки;
 *  - отсутствие `revision` (одобрение, off-graph мутация) — это `undefined`, а не
 *    «пустой diff»: красит клиент только то, что сервер назвал индексами.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { HitlCards, type HitlResolvedEvent } from '../../src/components/HitlCards';
import type {
  ContentDocument,
  DocumentRevision,
  HITLCardView,
  HitlRespondResponse,
} from '../../src/types/contentDocument';

const respondHitlCard = vi.fn<() => Promise<HitlRespondResponse>>();

vi.mock('../../src/api/client', () => ({
  respondHitlCard: () => respondHitlCard(),
  fetchHitlStepUpChallenge: async () => ({ required: false, method: 'none' }),
}));

function doc(...texts: string[]): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: null,
    blocks: texts.map(text => ({ type: 'paragraph', text })),
    actions: [],
    meta: { confidence: 0.9, requires_review: false, source_refs: [] },
  };
}

function revision(): DocumentRevision {
  return {
    revision_of: 'prev-hash',
    changed_blocks: ['b1'],
    changed_block_indices: [0],
    removed_blocks: ['gone'],
    unchanged_blocks: 1,
  };
}

function card(overrides: Partial<HITLCardView> = {}): HITLCardView {
  return {
    card_id: 'card-1',
    thread_id: 'thread-1',
    task_id: 'task-1',
    purpose: 'quality_review',
    title: 'Проверьте ответ',
    options: [
      {
        action_id: 'reject',
        label: 'Доработать',
        kind: 'custom',
        style: 'primary',
        action_token: 'token-token-token-token-1234',
      },
    ],
    risk_score: 0.4,
    status: 'pending',
    created_at: '2026-01-01T00:00:00+00:00',
    expires_at: '2099-01-01T00:00:00+00:00',
    ...overrides,
  };
}

function respondWith(resumed: HitlRespondResponse['resumed'], rev: DocumentRevision | null) {
  respondHitlCard.mockResolvedValue({
    resolve: { card: card({ status: 'resolved' }), replayed: false, message: 'ok' },
    resumed,
    revision: rev,
  });
}

describe('HitlCards resolved event', () => {
  it('carries the revision next to the replacement document', async () => {
    const events: HitlResolvedEvent[] = [];
    respondWith(
      {
        task_id: 'task-1',
        agent_role: 'formatter',
        status: 'success',
        confidence: 0.9,
        requires_review: false,
        error: null,
        output: doc('Исправлено.'),
        hitl_cards: [],
      } as never,
      revision()
    );

    render(<HitlCards cards={[card()]} onResolved={event => events.push(event)} />);
    fireEvent.click(screen.getByRole('button', { name: /Доработать/ }));

    await waitFor(() => expect(events).toHaveLength(1));
    expect(events[0].resumed?.output?.blocks).toHaveLength(1);
    expect(events[0].revision?.changed_block_indices).toEqual([0]);
  });

  it('leaves the revision absent when the resume produced no diff', async () => {
    const events: HitlResolvedEvent[] = [];
    respondWith(
      {
        task_id: 'task-1',
        agent_role: 'formatter',
        status: 'success',
        confidence: 0.9,
        requires_review: false,
        error: null,
        output: doc('Новый ответ.'),
        hitl_cards: [],
      } as never,
      null
    );

    render(<HitlCards cards={[card()]} onResolved={event => events.push(event)} />);
    fireEvent.click(screen.getByRole('button', { name: /Доработать/ }));

    await waitFor(() => expect(events).toHaveLength(1));
    expect(events[0].revision).toBeNull();
  });
});
