import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installMatchMediaStub } from '../match-media';

/**
 * `prefers-reduced-motion` в иконке (084, WCAG 2.2.2).
 *
 * Контракт выбора рендерера: движение разрешено — Lottie, выключено — статичный
 * Lucide-глиф. Приостановленный Lottie сознательно НЕ используется: без
 * `autoplay` библиотека не рисует ни одного кадра, и статус пропадал бы целиком.
 *
 * Здесь проверяется именно выбор компонента, а не пиксели: движение Lottie
 * живёт в реальном браузере (`e2e/a11y.spec.ts`).
 */
const mounts = vi.hoisted(() => [] as Array<Record<string, unknown>>);

vi.mock('lottie-react', async () => {
  const { useRef } = await import('react');
  return {
    LottieLight: (props: Record<string, unknown>) => {
      // «Журнал монтирований»: запись ровно один раз на инстанс, поэтому длина
      // списка доказывает монтирование, а не обновление пропсов.
      const startedRef = useRef(false);
      if (!startedRef.current) {
        startedRef.current = true;
        mounts.push(props);
      }
      return null;
    },
  };
});

const { TokenIcon } = await import('../../src/icons/TokenIcon');

/** Управляемый `MediaQueryList`: смена настройки доставляется подписчикам. */
function installControllableMatchMedia(initial: boolean) {
  const listeners = new Set<() => void>();
  let matches = initial;

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (): MediaQueryList =>
      ({
        get matches() {
          return matches;
        },
        media: '(prefers-reduced-motion: reduce)',
        onchange: null,
        addEventListener: (_type: string, listener: () => void) => {
          listeners.add(listener);
        },
        removeEventListener: (_type: string, listener: () => void) => {
          listeners.delete(listener);
        },
        addListener: (listener: () => void) => {
          listeners.add(listener);
        },
        removeListener: (listener: () => void) => {
          listeners.delete(listener);
        },
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  });

  return {
    set(next: boolean) {
      matches = next;
      for (const listener of listeners) listener();
    },
  };
}

describe('TokenIcon under prefers-reduced-motion', () => {
  afterEach(() => {
    mounts.length = 0;
    // Глобальная заглушка из setup возвращается на место: иначе следующий файл
    // унаследовал бы управляемый matchMedia этого теста.
    installMatchMediaStub();
  });

  it('animates when motion is allowed', () => {
    installControllableMatchMedia(false);
    const { container } = render(<TokenIcon token="info" animated />);
    expect(mounts).toHaveLength(1);
    expect(container.firstElementChild?.classList.contains('token-lottie')).toBe(true);
  });

  it('plays the status animation once, never on loop (WCAG 2.2.2)', () => {
    installControllableMatchMedia(false);
    render(<TokenIcon token="success" animated />);
    // Иконка стартует сама: бесконечный цикл рядом с читаемым текстом — под
    // запретом 2.2.2, а «статус» первым проходом уже сообщён.
    expect(mounts[0]?.loop).toBe(false);
  });

  it('starts the animation explicitly — the library defaults to autoplay=false', () => {
    installControllableMatchMedia(false);
    render(<TokenIcon token="info" animated />);
    // Регрессия: без явного `autoplay` lottie-react рисует первый кадр и стоит,
    // иконка «анимированная» только по имени.
    expect(mounts[0]?.autoplay).toBe(true);
  });

  it('renders the static Lucide glyph when motion is reduced — never a paused Lottie', () => {
    installControllableMatchMedia(true);
    const { container } = render(<TokenIcon token="info" animated />);

    expect(mounts).toHaveLength(0);
    expect(container.querySelector('.token-lottie')).toBeNull();
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    // Класс остаётся: CSS под reduced-motion его просто гасит.
    expect(svg?.getAttribute('class') ?? '').toContain('icon-animated');
  });

  it('switches renderer when the setting changes while the widget is live', () => {
    const media = installControllableMatchMedia(false);
    const { container } = render(<TokenIcon token="info" animated />);
    expect(mounts).toHaveLength(1);

    act(() => media.set(true));

    expect(container.querySelector('.token-lottie')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
    // Обратно: настройку вернули — Lottie снова анимируется.
    act(() => media.set(false));
    expect(container.querySelector('.token-lottie')).not.toBeNull();
  });

  it('keeps content tokens static whatever the setting says', () => {
    installControllableMatchMedia(false);
    const { container } = render(<TokenIcon token="calendar" animated />);
    expect(container.querySelector('.token-lottie')).toBeNull();
    expect(mounts).toHaveLength(0);
  });
});
