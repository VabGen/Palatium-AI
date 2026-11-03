import { useSyncExternalStore } from 'react';

/**
 * `prefers-reduced-motion` (084): движение — украшение, а не информация.
 *
 * Отдельный модуль, а не хук внутри `TokenIcon`: тот же сигнал понадобится
 * любому будущему движению (орб перешёл на статичный кадр по контракту
 * библиотеки, Lottie — через `autoplay`), и второй источник правды о media-query
 * разошёлся бы с первым.
 *
 * Чтение — `useSyncExternalStore`, как в `theme.ts`: снимок берётся на рендере,
 * поэтому первый кадр уже статичен и мигания «анимация → стоп» нет. Слушатели
 * подписываются на сам `MediaQueryList`, а не на `resize`: только он сообщает
 * о смене настройки ОС при живом окне.
 */
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

/** `null`, когда media-запросов нет (SSR, тесты без заглушки). */
function mediaQueryList(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(REDUCED_MOTION_QUERY);
}

function subscribe(onStoreChange: () => void): () => void {
  const media = mediaQueryList();
  if (!media) return () => undefined;
  media.addEventListener('change', onStoreChange);
  return () => media.removeEventListener('change', onStoreChange);
}

function getSnapshot(): boolean {
  return mediaQueryList()?.matches ?? false;
}

/** Сервер рендерит статичный вариант: анимация без JS — не движение, а картинка. */
function getServerSnapshot(): boolean {
  return false;
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
