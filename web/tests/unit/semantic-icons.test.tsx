/**
 * Semantic icon derivation (W7): the renderer falls back to `iconFor*` only when the
 * block carries no explicit `icon` — an explicit icon always wins.
 *
 * The atom (`TokenIcon`) stays dumb: it never knows about CalloutBlock / StepItem /
 * ActionSpec, so the mapping and its priority are asserted here, at the renderer.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import { HitlCards } from '../../src/components/HitlCards';
import { TokenIcon } from '../../src/icons/TokenIcon';
import { iconForActionKind, iconForStepStatus, iconForTone } from '../../src/icons/semanticIcons';
import type {
  ActionKind,
  CalloutTone,
  ContentDocument,
  HITLCardView,
  IconToken,
  StepStatus,
} from '../../src/types/contentDocument';

/** How an icon actually renders: Lottie wrapper, or the Lucide SVG paths. */
type Mark = { lottie: boolean; svg: string | null };

function markOf(root: Element | null | undefined): Mark {
  if (!root) return { lottie: false, svg: null };
  if (root.classList.contains('token-lottie')) return { lottie: true, svg: null };
  const svg = root.tagName.toLowerCase() === 'svg' ? root : root.querySelector('svg');
  return { lottie: false, svg: svg?.innerHTML ?? null };
}

function expectedIcon(token: IconToken | null, size: number, animated = false): Mark {
  if (token === null) return { lottie: false, svg: null };
  const { container } = render(<TokenIcon token={token} size={size} animated={animated} />);
  return markOf(container.firstElementChild);
}

function docWith(blocks: ContentDocument['blocks']): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks,
    actions: [],
    meta: { confidence: 1, requires_review: false, source_refs: [], interaction: 'none' },
  };
}

function calloutIcon(tone: CalloutTone, icon?: IconToken): Mark {
  const { container } = render(
    <BlockRenderer document={docWith([{ type: 'callout', tone, body: 'body', icon }])} />
  );
  return markOf(container.querySelector('.block-callout')?.firstElementChild);
}

function stepIcon(status: StepStatus | null, icon?: IconToken): Mark {
  const { container } = render(
    <BlockRenderer
      document={docWith([{ type: 'steps', items: [{ title: 't', body: 'b', status, icon }] }])}
    />
  );
  return markOf(container.querySelector('.step-marker')?.firstElementChild);
}

/** Текст всех маркеров: номер у шага без состояния, пусто у шага с иконкой. */
function stepMarkerTexts(count: number): string[] {
  const { container } = render(
    <BlockRenderer
      document={docWith([
        {
          type: 'steps',
          items: Array.from({ length: count }, (_, i) => ({ title: `t${i + 1}`, body: 'b' })),
        },
      ])}
    />
  );
  return [...container.querySelectorAll('.step-marker')].map(
    marker => marker.textContent?.trim() ?? ''
  );
}

function hitlCard(options: HITLCardView['options']): HITLCardView {
  return {
    card_id: 'card-1',
    thread_id: 'thread-1',
    task_id: 'task-1',
    purpose: 'quality_review',
    title: 'Review',
    options,
    risk_score: 0.2,
    status: 'pending',
    created_at: '2026-10-30T09:00:00Z',
    expires_at: '2026-10-30T09:30:00Z',
  };
}

function actionIcon(kind: ActionKind, icon?: IconToken | null): Mark {
  const { container } = render(
    <HitlCards
      cards={[
        hitlCard([
          {
            action_id: 'a1',
            label: 'Approve',
            kind,
            style: 'secondary',
            icon: icon ?? null,
            action_token: 'x'.repeat(32),
          },
        ]),
      ]}
      onResolved={() => undefined}
    />
  );
  return markOf(container.querySelector('.action-card')?.firstElementChild);
}

describe('semantic icon tables', () => {
  it('maps callout tones', () => {
    expect(iconForTone('info')).toBe('info');
    expect(iconForTone('success')).toBe('success');
    expect(iconForTone('warning')).toBe('warning');
    expect(iconForTone('danger')).toBe('danger');
  });

  it('maps step statuses', () => {
    expect(iconForStepStatus('pending')).toBe('clock');
    expect(iconForStepStatus('active')).toBe('clock');
    expect(iconForStepStatus('done')).toBe('success');
    expect(iconForStepStatus('blocked')).toBe('x');
  });

  it('derives no step icon when there is no status', () => {
    // Отсутствие статуса — не «ожидание»: иначе у каждой строки перечня
    // появлялись бы одинаковые часы (регрессия: список из 9 компонентов).
    expect(iconForStepStatus(null)).toBeNull();
    expect(iconForStepStatus(undefined)).toBeNull();
  });

  it('maps action kinds, custom opts out of derivation', () => {
    expect(iconForActionKind('approve')).toBe('check');
    expect(iconForActionKind('reject')).toBe('x');
    expect(iconForActionKind('confirm')).toBe('check');
    expect(iconForActionKind('dismiss')).toBe('x');
    expect(iconForActionKind('format')).toBe('edit');
    expect(iconForActionKind('custom')).toBeNull();
  });
});

describe('callout icon derivation', () => {
  for (const tone of ['info', 'success', 'warning', 'danger'] as const) {
    it(`derives ${tone} from tone when icon is absent`, () => {
      expect(calloutIcon(tone)).toEqual(expectedIcon(iconForTone(tone), 18, true));
    });
  }

  it('explicit icon wins over tone', () => {
    expect(calloutIcon('danger', 'mail')).toEqual(expectedIcon('mail', 18, true));
  });
});

describe('step icon derivation', () => {
  for (const status of ['pending', 'active', 'done', 'blocked'] as const) {
    it(`derives ${status} from status when icon is absent`, () => {
      expect(stepIcon(status)).toEqual(expectedIcon(iconForStepStatus(status), 16));
    });
  }

  it('explicit icon wins over status', () => {
    expect(stepIcon('done', 'mail')).toEqual(expectedIcon('mail', 16));
  });

  /**
   * Регрессия на реальный случай: перечень из 9 компонентов разбирался как
   * timeline, парсер ставил `pending` каждой строке, и все строки получали
   * одинаковую иконку часов — не по теме. Без статуса маркер обязан показывать
   * номер: это единственный факт, который есть в данных.
   */
  it('numbers the marker when the step has no status', () => {
    expect(stepIcon(null)).toEqual({ lottie: false, svg: null });
    expect(stepMarkerTexts(9)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9']);
  });

  it('draws no status glyph at all when statuses are absent', () => {
    const { container } = render(
      <BlockRenderer
        document={docWith([
          {
            type: 'steps',
            items: [
              { title: 't1', body: 'b' },
              { title: 't2', body: 'b' },
            ],
          },
        ])}
      />
    );
    expect(container.querySelectorAll('.step-marker svg')).toHaveLength(0);
    // Класс статуса не выдумывается — CSS не подсвечивает «процесс» цветом.
    expect(container.querySelectorAll('.step[class*="status-"]')).toHaveLength(0);
  });
});

describe('HITL action icon derivation', () => {
  for (const kind of ['approve', 'reject', 'confirm', 'dismiss', 'format'] as const) {
    it(`derives an icon for kind=${kind}`, () => {
      const derived = iconForActionKind(kind);
      expect(derived).not.toBeNull();
      expect(actionIcon(kind)).toEqual(expectedIcon(derived, 16));
    });
  }

  it('custom renders without an icon and does not crash', () => {
    expect(actionIcon('custom')).toEqual({ lottie: false, svg: null });
  });

  it('explicit icon wins over kind', () => {
    expect(actionIcon('approve', 'mail')).toEqual(expectedIcon('mail', 16));
  });
});
