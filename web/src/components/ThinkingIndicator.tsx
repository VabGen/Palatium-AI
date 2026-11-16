import { useEffect, useRef } from 'react';
import { MODE_DRAWS, resolvePreset, type OrbSize } from 'thinking-orbs';
import { t } from '../i18n';
import { type PendingOrbState, type PendingPhase } from '../lib/pendingOrb';
import { useAppTheme } from '../lib/theme';

const ORB_SIZE: OrbSize = 64;

/**
 * Canvas-орб текущей фазы: геометрия `thinking-orbs`, RAF — наш и непрерывный.
 *
 * Пока `state` не сменился (`hop` → другая фаза), крутится анимация этого
 * режима; смена текста/режима только переключает preset, не «ждёт кадра».
 *
 * EXCEPTION: prefers-reduced-motion (084) — подтверждено пользователем 2026-11-12.
 * Заморозка орба между hop читалась как зависание; статус уже в видимой
 * подписи `role="status"`, орб остаётся непрерывным сигналом прогресса.
 */
function PendingOrbCanvas({ state }: { state: PendingOrbState }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const theme = useAppTheme(anchorRef);
  const dark = theme === 'dark';

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(2, typeof devicePixelRatio !== 'undefined' ? devicePixelRatio : 1);
    canvas.width = Math.round(ORB_SIZE * dpr);
    canvas.height = Math.round(ORB_SIZE * dpr);

    const { mode, speed, opts } = resolvePreset(state, ORB_SIZE);
    const draw = MODE_DRAWS[mode];

    const paint = (tSec: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, ORB_SIZE, ORB_SIZE);
      draw(ctx, ORB_SIZE, tSec, dark, opts);
    };

    let raf = 0;
    let running = false;

    const loop = () => {
      paint((performance.now() / 1000) * speed);
      if (running) raf = requestAnimationFrame(loop);
    };

    const start = () => {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(loop);
    };

    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    const onVis = () => {
      if (document.visibilityState === 'hidden') stop();
      else start();
    };

    document.addEventListener('visibilitychange', onVis);
    if (document.visibilityState !== 'hidden') start();
    else paint(0.6);

    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [state, dark]);

  return (
    <span className="thinking-indicator__orb" ref={anchorRef}>
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        width={ORB_SIZE}
        height={ORB_SIZE}
        style={{ width: ORB_SIZE, height: ORB_SIZE, display: 'block' }}
      />
    </span>
  );
}

/**
 * Индикатор работы агента: непрерывный орб текущей фазы + видимая подпись
 * шага графа (`hop` → `pendingPhaseForNode`). Орб и текст независимы: орб
 * анимируется, пока фаза та же; подпись меняется только на новом hop.
 *
 * `theme` через `useAppTheme` (не `auto` библиотеки): Shadow DOM + `data-theme`.
 */
export function ThinkingIndicator({ phase }: { phase: PendingPhase }) {
  return (
    <span className="thinking-indicator">
      <PendingOrbCanvas state={phase.state} />
      {/*
        `aria-live` задан явно: лента — `aria-live="off"`, смена фазы обязана
        звучать. `key` — перезапуск fade подписи без рестарта орба.
      */}
      <span
        key={phase.label}
        className="thinking-indicator__label"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {t(phase.label)}
      </span>
    </span>
  );
}
