/**
 * Persistable width for kimi dual-pane side-console (artifact / file preview).
 * Percent of ``.shell-workspace`` — matches live kimi ``--side-console-width``.
 */

export const SIDE_CONSOLE_WIDTH_DEFAULT = 70;
export const SIDE_CONSOLE_WIDTH_STORAGE_KEY = 'palatium:side-console-width-pct';

/** Matches ``--chat-split-min`` (35rem ≈ 560px at 16px root). */
export const SIDE_CONSOLE_CHAT_MIN_PX = 560;
/** Floor so the pane stays usable (aligned with ``--side-console-width-list``). */
export const SIDE_CONSOLE_PANE_MIN_PX = 320;

export function clampSideConsoleWidthPct(
  pct: number,
  workspaceWidth: number,
  chatMinPx = SIDE_CONSOLE_CHAT_MIN_PX,
  paneMinPx = SIDE_CONSOLE_PANE_MIN_PX
): number {
  if (!Number.isFinite(pct)) return SIDE_CONSOLE_WIDTH_DEFAULT;
  if (workspaceWidth <= 0) {
    return Math.min(80, Math.max(20, pct));
  }
  const maxPanePx = Math.max(paneMinPx, workspaceWidth - chatMinPx);
  const minPct = (paneMinPx / workspaceWidth) * 100;
  const maxPct = (maxPanePx / workspaceWidth) * 100;
  return Math.min(maxPct, Math.max(minPct, pct));
}

export function readSideConsoleWidthPct(): number {
  if (typeof localStorage === 'undefined') return SIDE_CONSOLE_WIDTH_DEFAULT;
  try {
    const raw = localStorage.getItem(SIDE_CONSOLE_WIDTH_STORAGE_KEY);
    if (raw == null) return SIDE_CONSOLE_WIDTH_DEFAULT;
    const parsed = Number.parseFloat(raw);
    if (!Number.isFinite(parsed)) return SIDE_CONSOLE_WIDTH_DEFAULT;
    return clampSideConsoleWidthPct(parsed, 0);
  } catch {
    return SIDE_CONSOLE_WIDTH_DEFAULT;
  }
}

export function writeSideConsoleWidthPct(pct: number): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(SIDE_CONSOLE_WIDTH_STORAGE_KEY, String(Math.round(pct * 10) / 10));
  } catch {
    // Private mode / quota — width stays session-scoped via React state.
  }
}
