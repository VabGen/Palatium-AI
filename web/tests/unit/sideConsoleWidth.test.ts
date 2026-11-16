import { describe, expect, it } from 'vitest';

import {
  clampSideConsoleWidthPct,
  SIDE_CONSOLE_CHAT_MIN_PX,
  SIDE_CONSOLE_PANE_MIN_PX,
  SIDE_CONSOLE_WIDTH_DEFAULT,
} from '../../src/lib/sideConsoleWidth';

describe('clampSideConsoleWidthPct', () => {
  it('keeps chat min and pane min inside a wide workspace', () => {
    const workspace = 1400;
    const maxPct = ((workspace - SIDE_CONSOLE_CHAT_MIN_PX) / workspace) * 100;
    const minPct = (SIDE_CONSOLE_PANE_MIN_PX / workspace) * 100;
    expect(clampSideConsoleWidthPct(95, workspace)).toBeCloseTo(maxPct, 5);
    expect(clampSideConsoleWidthPct(5, workspace)).toBeCloseTo(minPct, 5);
    // 70% default fits only when workspace is wide enough for chat-min + 70%.
    expect(clampSideConsoleWidthPct(SIDE_CONSOLE_WIDTH_DEFAULT, workspace)).toBeCloseTo(
      Math.min(SIDE_CONSOLE_WIDTH_DEFAULT, maxPct),
      5
    );
    expect(clampSideConsoleWidthPct(SIDE_CONSOLE_WIDTH_DEFAULT, 2000)).toBe(
      SIDE_CONSOLE_WIDTH_DEFAULT
    );
  });

  it('falls back to a safe band when workspace width is unknown', () => {
    expect(clampSideConsoleWidthPct(12, 0)).toBe(20);
    expect(clampSideConsoleWidthPct(99, 0)).toBe(80);
  });
});
