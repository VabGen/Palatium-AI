import { useCallback, useSyncExternalStore } from 'react';
import type { RefObject } from 'react';

export type AppTheme = 'dark' | 'light';

/**
 * Элемент, на котором объявлена тема приложения, для узла внутри `element`.
 *
 * Контракт темы — `tokens.css`: светлая включается ТОЛЬКО атрибутом
 * `data-theme="light"`, тёмная — дефолт. Системная `prefers-color-scheme` сюда
 * не входит: она описывает настройку ОС, а не тему хоста, и в светлой СЭД дала бы
 * тёмный виджет.
 *
 * Виджет живёт в Shadow DOM, поэтому обход предков (`closest`, `parentElement`)
 * до `data-theme` на shadow host'е НЕ доходит — берём scope через `getRootNode()`:
 * `documentElement` для standalone-страницы или хост `<palatium-assistant>`.
 */
export function themeScope(element: Element): Element {
  const root = element.getRootNode();
  return root instanceof ShadowRoot ? root.host : document.documentElement;
}

/** Тема по атрибуту `data-theme`; всё, кроме явного `light`, — тёмная. */
export function resolveAppTheme(scope: Element): AppTheme {
  return scope.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

/**
 * Текущая тема приложения, реактивно на смену `data-theme` у её scope.
 *
 * `anchorRef` — любой узел внутри приложения/виджета: по нему определяется scope
 * (см. `themeScope`), поэтому хук работает и в standalone, и в Shadow DOM.
 * Подписка на DOM-атрибут идёт через `useSyncExternalStore`, а не через
 * `useState`+эффект: снимок читается в рендере, поэтому первый кадр уже получает
 * фактическую тему, без промежуточного состояния.
 */
export function useAppTheme(anchorRef: RefObject<HTMLElement | null>): AppTheme {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const element = anchorRef.current;
      if (!element) return () => undefined;

      // Наблюдаем сам scope, а не документ: в Shadow DOM мутации хоста хоть и
      // видны документу, но `data-theme` на `:host` — единственный сигнал темы.
      const observer = new MutationObserver(onChange);
      observer.observe(themeScope(element), { attributes: true, attributeFilter: ['data-theme'] });
      return () => observer.disconnect();
    },
    [anchorRef]
  );

  const getSnapshot = useCallback(() => {
    const element = anchorRef.current;
    return element ? resolveAppTheme(themeScope(element)) : 'dark';
  }, [anchorRef]);

  return useSyncExternalStore(subscribe, getSnapshot);
}
