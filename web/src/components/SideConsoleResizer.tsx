/**
 * Dual-pane drag handle (kimi side-console ↔ chat).
 * Visual: hairline + centered pill grip (Color System / Separators).
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react';
import { t } from '../i18n';
import { clampSideConsoleWidthPct, SIDE_CONSOLE_WIDTH_DEFAULT } from '../lib/sideConsoleWidth';

export type SideConsoleResizerProps = {
  workspaceRef: RefObject<HTMLElement | null>;
  widthPercent: number;
  onWidthPercentChange: (pct: number) => void;
  onReset?: () => void;
};

function workspaceMetrics(root: HTMLElement | null): { left: number; width: number } {
  if (!root) return { left: 0, width: 0 };
  const rect = root.getBoundingClientRect();
  return { left: rect.left, width: rect.width };
}

export function SideConsoleResizer({
  workspaceRef,
  widthPercent,
  onWidthPercentChange,
  onReset,
}: SideConsoleResizerProps) {
  const hitRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragOrigin = useRef<{ startX: number; startPct: number; width: number } | null>(null);

  const applyClientX = useCallback(
    (clientX: number, origin: { startX: number; startPct: number; width: number }) => {
      if (origin.width <= 0) return;
      const deltaPx = origin.startX - clientX;
      const nextPct = origin.startPct + (deltaPx / origin.width) * 100;
      onWidthPercentChange(clampSideConsoleWidthPct(nextPct, origin.width));
    },
    [onWidthPercentChange]
  );

  useEffect(() => {
    if (!dragging) return;

    function onMove(event: PointerEvent) {
      const origin = dragOrigin.current;
      if (!origin) return;
      applyClientX(event.clientX, origin);
    }

    function onUp() {
      dragOrigin.current = null;
      setDragging(false);
      document.body.classList.remove('is-side-console-resizing');
    }

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      document.body.classList.remove('is-side-console-resizing');
    };
  }, [dragging, applyClientX]);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const { width } = workspaceMetrics(workspaceRef.current);
    if (width <= 0) return;
    event.preventDefault();
    hitRef.current?.setPointerCapture(event.pointerId);
    dragOrigin.current = {
      startX: event.clientX,
      startPct: widthPercent,
      width,
    };
    setDragging(true);
    document.body.classList.add('is-side-console-resizing');
  }

  function onDoubleClick() {
    if (onReset) {
      onReset();
      return;
    }
    const { width } = workspaceMetrics(workspaceRef.current);
    onWidthPercentChange(clampSideConsoleWidthPct(SIDE_CONSOLE_WIDTH_DEFAULT, width));
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const { width } = workspaceMetrics(workspaceRef.current);
    const step = event.shiftKey ? 5 : 2;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      onWidthPercentChange(clampSideConsoleWidthPct(widthPercent + step, width));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      onWidthPercentChange(clampSideConsoleWidthPct(widthPercent - step, width));
    } else if (event.key === 'Home') {
      event.preventDefault();
      onWidthPercentChange(clampSideConsoleWidthPct(80, width));
    } else if (event.key === 'End') {
      event.preventDefault();
      onWidthPercentChange(clampSideConsoleWidthPct(20, width));
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onDoubleClick();
    }
  }

  const valueNow = Math.round(widthPercent);

  return (
    <div className={`side-console-resizer${dragging ? ' is-active' : ''}`} aria-hidden={false}>
      <div
        ref={hitRef}
        className="side-console-resizer__hit"
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={20}
        aria-valuemax={80}
        aria-valuenow={valueNow}
        aria-label={t('a11y.sideConsoleResize')}
        title={t('a11y.sideConsoleResizeHint')}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
      >
        <span className="side-console-resizer__grip" aria-hidden />
      </div>
    </div>
  );
}
