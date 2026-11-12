import { useRef } from 'react';
import { ThinkingOrb } from 'thinking-orbs';
import { t } from '../i18n';
import { type PendingPhase } from '../lib/pendingOrb';
import { useAppTheme } from '../lib/theme';

/**
 * Индикатор работы агента: canvas-орб [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs).
 *
 * 64px — chat-avatar preset библиотеки (не scale от 40). Орб в колонке будущего
 * ответа → без layout shift при первом токене. Фаза графа → `state` орба;
 * русская подпись только через `role="status"` (084).
 *
 * `theme` явно (не `auto`): `auto` обходит предков через `parentElement` и не
 * пересекает Shadow DOM → падает на `prefers-color-scheme`, чего `tokens.css`
 * не принимает (тема только через `data-theme` хоста).
 */
export function ThinkingIndicator({ phase }: { phase: PendingPhase }) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const theme = useAppTheme(anchorRef);

  return (
    <span className="thinking-indicator" ref={anchorRef}>
      {/*
         `role="img"` орба озвучил бы состояние вторым, англоязычным label'ом —
         русскую фазу даёт соседний `role="status"`.
      */}
      <ThinkingOrb state={phase.state} size={64} theme={theme} aria-hidden="true" />
      {/*
        `aria-live` задан явно: лента сообщений — `aria-live="off"`, а смена
        фазы обязана звучать. Явное значение на элементе сильнее наследуемого.
      */}
      <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {t(phase.label)}
      </span>
    </span>
  );
}
