import { useCallback, useSyncExternalStore } from 'react';
import type { RefObject } from 'react';

export type AppTheme = 'dark' | 'light';

/**
 * Элемент, на котором объявлена тема приложения, для узла внутри `element`.
 *
 * Product parity 2026-11-06: default = **light** (Kimi product screenshots).
 * Тёмная — только явный `data-theme="dark"`. Системная `prefers-color-scheme`
 * не участвует (хост/СЭД задают тему атрибутом).
 *
 * Виджет в Shadow DOM: scope через `getRootNode()` → shadow host или
 * `document.documentElement`.
 */
export function themeScope(element: Element): Element {
  const root = element.getRootNode();
  return root instanceof ShadowRoot ? root.host : document.documentElement;
}

/** Тема по атрибуту; всё, кроме явного `dark`, — светлая. */
export function resolveAppTheme(scope: Element): AppTheme {
  return scope.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

/** Выставить светлую тему по умолчанию, если хост ещё не задал `data-theme`. */
export function ensureDefaultTheme(scope: Element): void {
  if (!scope.hasAttribute('data-theme')) {
    scope.setAttribute('data-theme', 'light');
  }
}

/**
 * Текущая тема приложения, реактивно на смену `data-theme` у её scope.
 */
export function useAppTheme(anchorRef: RefObject<HTMLElement | null>): AppTheme {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const element = anchorRef.current;
      if (!element) return () => undefined;

      const observer = new MutationObserver(onChange);
      observer.observe(themeScope(element), { attributes: true, attributeFilter: ['data-theme'] });
      return () => observer.disconnect();
    },
    [anchorRef]
  );

  const getSnapshot = useCallback(() => {
    const element = anchorRef.current;
    return element ? resolveAppTheme(themeScope(element)) : 'light';
  }, [anchorRef]);

  return useSyncExternalStore(subscribe, getSnapshot);
}
