import { fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { DialogueNav } from '../../src/components/DialogueNav';
import { dialogueTurnDomId } from '../../src/lib/dialogueNav';
import { t } from '../../src/i18n';

beforeAll(() => {
  class MockIntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
});

describe('DialogueNav', () => {
  it('jumps to turn id on item click', () => {
    const scrollRootRef = createRef<HTMLDivElement>();
    const onJump = vi.fn();
    const scrollIntoView = vi.fn();

    const { container } = render(
      <div>
        <div ref={scrollRootRef} className="transcript">
          <div id={dialogueTurnDomId('u1')} data-turn-id="u1">
            first
          </div>
          <div id={dialogueTurnDomId('u2')} data-turn-id="u2">
            second
          </div>
        </div>
        <DialogueNav
          entries={[
            {
              id: 'u1',
              label: 'табл2026.xlsx о чем файл',
              fileName: 'табл2026.xlsx',
              extraCount: 0,
              prompt: 'о чем файл',
              iconKind: 'xlsx',
              hasFile: true,
            },
            {
              id: 'u2',
              label: 'дай анализ скан1',
              fileName: null,
              extraCount: 0,
              prompt: 'дай анализ скан1',
              iconKind: 'text',
              hasFile: false,
            },
          ]}
          scrollRootRef={scrollRootRef}
          onJump={onJump}
        />
      </div>
    );

    const target = container.querySelector(`#${dialogueTurnDomId('u2')}`);
    expect(target).toBeTruthy();
    if (target) {
      Object.defineProperty(target, 'scrollIntoView', {
        value: scrollIntoView,
        configurable: true,
      });
    }

    fireEvent.click(screen.getByRole('button', { name: 'дай анализ скан1' }));
    expect(onJump).toHaveBeenCalledWith('u2');
    expect(scrollIntoView).toHaveBeenCalled();
    expect(screen.getByRole('navigation', { name: t('a11y.dialogueNav') })).toBeInTheDocument();
  });
});
