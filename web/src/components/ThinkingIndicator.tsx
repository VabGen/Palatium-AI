import { useRef } from 'react';
import { ThinkingOrb } from 'thinking-orbs';
import { t } from '../i18n';
import { type PendingPhase } from '../lib/pendingOrb';
import { useAppTheme } from '../lib/theme';

/**
 * Индикатор работы агента: только орб, без облака и подписи.
 *
 * Это и есть «марка ассистента в момент работы» (ChatGPT / Claude / Gemini):
 * 64px — единственный размер, отрисованный и выверенный вручную. Орб стоит в
 * колонке будущего ответа, поэтому первый токен не сдвигает текст по
 * горизонтали: облако появляется на том же левом крае, аватар — в свободной
 * левой колонке.
 *
 * Подпись не видна, но существует: `role="status"` объявляет СМЕНУ фазы
 * скринридеру (084 — состояние нельзя передавать только картинкой), а при
 * `prefers-reduced-motion` она же показывается текстом, потому что движение
 * там выключено и остаётся единственным сигналом «идёт работа».
 *
 * `theme` передаётся явно, а не `theme="auto"`. В библиотеке `auto` обходит
 * предков через `parentElement`, а границу Shadow DOM так не перейти; не найдя
 * `data-theme`, он падает на `prefers-color-scheme` — сигнал, который контракт
 * `tokens.css` отвергает (светлая тема — только явный opt-in хоста).
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
      <span className="sr-only" role="status">
        {t(phase.label)}
      </span>
    </span>
  );
}
