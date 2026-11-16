/**
 * Shell density from **panel width**, not viewport.
 *
 * SED/host embed: chat sits in a ~400px right rail while the host page may be
 * 1920px — viewport media queries would miss compact/narrow. Measure `.shell`.
 */

/** Drawer / off-canvas nav (kimi P5). */
export const SHELL_NARROW_MAX_PX = 1280;

/**
 * SED side-panel densification (~400px). Typography + padding tighten;
 * composer textarea stays ≥16px (iOS zoom).
 */
export const SHELL_COMPACT_MAX_PX = 480;

export type ShellDensity = {
  narrow: boolean;
  compact: boolean;
};

export function shellDensityFromWidth(width: number): ShellDensity {
  const w = Number.isFinite(width) && width > 0 ? width : Number.POSITIVE_INFINITY;
  return {
    narrow: w <= SHELL_NARROW_MAX_PX,
    compact: w <= SHELL_COMPACT_MAX_PX,
  };
}

/** Bootstrap before first layout: fall back to viewport when shell is unmounted. */
export function initialShellDensity(): ShellDensity {
  if (typeof window === 'undefined') {
    return { narrow: false, compact: false };
  }
  return shellDensityFromWidth(window.innerWidth);
}
