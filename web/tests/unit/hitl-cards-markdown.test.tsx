import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HitlCards } from '../../src/components/HitlCards';
import type { HITLCardView } from '../../src/types/contentDocument';

vi.mock('../../src/api/client', () => ({
  fetchHitlStepUpChallenge: vi.fn(),
  respondHitlCard: vi.fn(),
}));

const baseCard: HITLCardView = {
  card_id: 'card-1',
  thread_id: 'th-1',
  task_id: 'task-1',
  purpose: 'user_choice',
  title: 'Выберите один вариант',
  body: 'Ответ без подтверждения во внешних источниках.',
  options: [
    {
      action_id: 'opt_1',
      label: '**Планами счетов** бухгалтерского учета;',
      kind: 'custom',
      style: 'secondary',
      action_token: 'tok-1',
    },
  ],
  risk_score: 0.2,
  status: 'pending',
  created_at: '2026-01-01T00:00:00Z',
  expires_at: '2099-01-01T01:00:00Z',
};

describe('HitlCards markdown', () => {
  it('renders option label bold without raw ** markers', () => {
    render(<HitlCards cards={[baseCard]} onResolved={() => undefined} />);
    expect(screen.queryByText(/\*\*Планами счетов\*\*/)).toBeNull();
    const strong = screen.getByText('Планами счетов');
    expect(strong.tagName).toBe('STRONG');
  });
});
