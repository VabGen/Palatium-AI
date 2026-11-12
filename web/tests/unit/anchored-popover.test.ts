import { describe, expect, it } from 'vitest';
import { placePopover } from '../../src/components/ui/useAnchoredPopover';

const rect = (top: number, left: number, width: number, height: number) => ({
  top,
  left,
  right: left + width,
  bottom: top + height,
  width,
  height,
});

const VIEWPORT = { width: 1200, height: 800 };

describe('placePopover', () => {
  it('opens below the trigger when the panel fits', () => {
    const placed = placePopover(
      rect(100, 100, 120, 36),
      { width: 260, height: 200 },
      {
        side: 'bottom',
        align: 'start',
        viewport: VIEWPORT,
      }
    );

    expect(placed.side).toBe('bottom');
    expect(placed.top).toBe(144); // 100 + 36 + 8
    expect(placed.left).toBe(100);
  });

  it('flips above when the panel does not fit below', () => {
    const placed = placePopover(
      rect(700, 100, 120, 36),
      { width: 260, height: 200 },
      {
        side: 'bottom',
        align: 'start',
        viewport: VIEWPORT,
      }
    );

    expect(placed.side).toBe('top');
    expect(placed.top).toBe(492); // 700 - 8 - 200
    expect(placed.top + placed.height).toBeLessThanOrEqual(rect(700, 100, 120, 36).top - 8 + 0.001);
  });

  it('caps the height to the roomier side when neither side fits', () => {
    const trigger = rect(600, 100, 120, 36);
    const placed = placePopover(
      trigger,
      { width: 260, height: 500 },
      {
        side: 'bottom',
        align: 'start',
        viewport: VIEWPORT,
      }
    );

    expect(placed.side).toBe('top');
    expect(placed.maxHeight).toBeLessThanOrEqual(592);
    expect(placed.top).toBeGreaterThanOrEqual(8);
    expect(placed.top + placed.height).toBeLessThanOrEqual(VIEWPORT.height - 8);
  });

  it('clamps a start-aligned panel to the right edge instead of clipping it', () => {
    const placed = placePopover(
      rect(100, 1000, 120, 36),
      { width: 290, height: 200 },
      {
        side: 'bottom',
        align: 'start',
        viewport: VIEWPORT,
      }
    );

    expect(placed.left).toBe(VIEWPORT.width - 290 - 8);
    expect(placed.left + placed.width).toBeLessThanOrEqual(VIEWPORT.width - 8);
  });

  it('clamps an end-aligned panel to the left edge', () => {
    const placed = placePopover(
      rect(100, 20, 120, 36),
      { width: 290, height: 200 },
      {
        side: 'bottom',
        align: 'end',
        viewport: VIEWPORT,
      }
    );

    expect(placed.left).toBe(8);
  });

  it('shrinks a panel wider than the viewport to the gutters', () => {
    const placed = placePopover(
      rect(100, 10, 60, 36),
      { width: 900, height: 120 },
      {
        side: 'bottom',
        align: 'start',
        viewport: { width: 430, height: 800 },
      }
    );

    expect(placed.width).toBe(414); // 430 - 2 * 8
    expect(placed.left).toBe(8);
    expect(placed.left + placed.width).toBe(422);
  });

  it('opens a nested flyout to the left when the right side has no room', () => {
    const placed = placePopover(
      rect(300, 1000, 100, 32),
      { width: 200, height: 88 },
      {
        side: 'right',
        align: 'start',
        gap: 4,
        viewport: VIEWPORT,
      }
    );

    expect(placed.side).toBe('left');
    expect(placed.left).toBe(796); // 1000 - 4 - 200
  });

  it('keeps an upward flyout vertically inside the viewport', () => {
    const placed = placePopover(
      rect(20, 400, 100, 32),
      { width: 200, height: 300 },
      {
        side: 'right',
        align: 'end',
        gap: 4,
        viewport: VIEWPORT,
      }
    );

    expect(placed.top).toBe(8);
    expect(placed.top + placed.height).toBeLessThanOrEqual(VIEWPORT.height - 8);
  });
});
