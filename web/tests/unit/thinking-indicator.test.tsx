import { act, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { ThinkingIndicator } from '../../src/components/ThinkingIndicator';
import { t } from '../../src/i18n';
import { resolveAppTheme, themeScope, useAppTheme } from '../../src/lib/theme';

function ThemeProbe() {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const theme = useAppTheme(anchorRef);
  return <span ref={anchorRef} data-testid="probe" data-theme-name={theme} />;
}

describe('theme scope', () => {
  it('reads the light theme from data-theme only', () => {
    const scope = document.createElement('div');
    expect(resolveAppTheme(scope)).toBe('dark');
    scope.setAttribute('data-theme', 'light');
    expect(resolveAppTheme(scope)).toBe('light');
    scope.setAttribute('data-theme', 'dark');
    expect(resolveAppTheme(scope)).toBe('dark');
  });

  it('resolves the shadow host through the boundary', () => {
    const host = document.createElement('div');
    const shadow = host.attachShadow({ mode: 'open' });
    const inner = document.createElement('span');
    shadow.append(inner);

    expect(themeScope(inner)).toBe(host);
    expect(themeScope(document.body)).toBe(document.documentElement);
  });

  it('reacts to a host attribute switch inside shadow DOM', async () => {
    const host = document.createElement('div');
    document.body.append(host);
    const shadow = host.attachShadow({ mode: 'open' });
    const mount = document.createElement('div');
    shadow.append(mount);
    const root = createRoot(mount);

    await act(async () => root.render(<ThemeProbe />));
    expect(shadow.querySelector('[data-testid="probe"]')).toHaveAttribute(
      'data-theme-name',
      'dark'
    );

    // Светлая тема виджета объявляется на shadow host'е (`:host([data-theme])`),
    // а не в документе: обход предков библиотеки эту границу не переходит.
    await act(async () => {
      host.setAttribute('data-theme', 'light');
    });
    expect(shadow.querySelector('[data-testid="probe"]')).toHaveAttribute(
      'data-theme-name',
      'light'
    );

    await act(async () => root.unmount());
    host.remove();
  });
});

describe('ThinkingIndicator', () => {
  it('announces the phase through the live region, not the orb', () => {
    render(<ThinkingIndicator phase={{ state: 'searching', label: 'msg.pending.searching' }} />);

    const orb = document.querySelector('canvas');
    expect(orb).not.toBeNull();
    // Орб не должен дублировать состояние англоязычным `aria-label` библиотеки:
    // русскую фазу даёт соседний live-region.
    expect(orb).toHaveAttribute('aria-hidden', 'true');

    const status = screen.getByRole('status');
    expect(status).toHaveClass('sr-only');
    expect(status).toHaveTextContent(t('msg.pending.searching'));
  });

  it('keeps no visible caption next to the orb', () => {
    render(<ThinkingIndicator phase={{ state: 'composing', label: 'msg.pending.composing' }} />);

    // Единственный текст в индикаторе — скрытая подпись: облака и надписи нет.
    expect(document.querySelector('.thinking-indicator')?.textContent).toBe(
      t('msg.pending.composing')
    );
  });
});
