import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';

/** Gap between the trigger and the panel, matching kimi.ai's 4–8px rhythm. */
export const POPOVER_GAP = 8;
/** Minimum distance the panel keeps from the viewport edges. */
export const POPOVER_EDGE = 8;
/** Panel never collapses below this height — it scrolls instead. */
const MIN_PANEL_HEIGHT = 120;
const MIN_PANEL_WIDTH = 160;

export type PopoverSide = 'top' | 'bottom' | 'left' | 'right';
export type PopoverAlign = 'start' | 'end' | 'center';

export type PopoverPlacement = {
  side: PopoverSide;
  top: number;
  left: number;
  maxWidth: number;
  maxHeight: number;
  width: number;
  height: number;
};

type Rect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

/**
 * Places a panel against a trigger, clamped to the viewport.
 *
 * A panel that does not fit on its preferred side flips to the opposite one;
 * when neither side fits, it keeps the roomier side and caps its height so the
 * content scrolls instead of running past the screen edge. Horizontal position
 * is clamped to `POPOVER_EDGE` gutters, so a start-aligned menu near the right
 * edge slides left rather than being cut off.
 */
export function placePopover(
  trigger: Rect,
  panel: { width: number; height: number },
  options: {
    side?: PopoverSide;
    align?: PopoverAlign;
    gap?: number;
    edge?: number;
    viewport?: { width: number; height: number };
    /** Span the trigger's width (composer-wide panels like the slash menu). */
    matchWidth?: boolean;
    /**
     * Cross-axis anchor for left/right panels: kimi.ai hangs a flyout off the
     * *panel's* outer edge (4px), vertically centered on the hovered row. The
     * row alone would put it 4px inside the panel padding instead.
     */
    crossTrigger?: Rect;
  } = {}
): PopoverPlacement {
  const { side: preferred = 'bottom', align = 'start' } = options;
  const gap = options.gap ?? POPOVER_GAP;
  const edge = options.edge ?? POPOVER_EDGE;
  const viewport = options.viewport ?? {
    width: window.innerWidth,
    height: window.innerHeight,
  };

  const maxWidth = Math.max(MIN_PANEL_WIDTH, viewport.width - edge * 2);
  const maxHeight = Math.max(MIN_PANEL_HEIGHT, viewport.height - edge * 2);
  const width = options.matchWidth
    ? Math.min(trigger.width, maxWidth)
    : Math.min(panel.width, maxWidth);
  const height = Math.min(panel.height, maxHeight);

  const room = {
    bottom: viewport.height - trigger.bottom - gap - edge,
    top: trigger.top - gap - edge,
    right: viewport.width - trigger.right - gap - edge,
    left: trigger.left - gap - edge,
  };
  const opposite: Record<PopoverSide, PopoverSide> = {
    bottom: 'top',
    top: 'bottom',
    right: 'left',
    left: 'right',
  };
  const needed = preferred === 'top' || preferred === 'bottom' ? height : width;
  const fitsPreferred = room[preferred] >= needed;
  const fitsOpposite = room[opposite[preferred]] >= needed;
  /*
   * Preference first, then the opposite side if only that one fits, then the
   * roomier of the two — a panel that fits nowhere must still start from the
   * side with more space instead of always honouring the requested side.
   */
  const side = fitsPreferred
    ? preferred
    : fitsOpposite
      ? opposite[preferred]
      : room[opposite[preferred]] > room[preferred]
        ? opposite[preferred]
        : preferred;

  if (side === 'bottom' || side === 'top') {
    const available = Math.max(MIN_PANEL_HEIGHT, room[side]);
    const boxHeight = Math.min(height, available);
    const rawTop = side === 'bottom' ? trigger.bottom + gap : trigger.top - gap - boxHeight;
    // Never let a capped panel hang past the edge, whatever the trigger does.
    const top = clamp(rawTop, edge, viewport.height - boxHeight - edge);
    const desiredLeft = align === 'start' ? trigger.left : trigger.right - width;
    const left = clamp(desiredLeft, edge, viewport.width - width - edge);
    return {
      side,
      top,
      left,
      maxWidth: options.matchWidth ? width : maxWidth,
      maxHeight: available,
      width,
      height: boxHeight,
    };
  }

  const available = Math.max(MIN_PANEL_WIDTH, room[side]);
  const boxWidth = Math.min(width, available);
  const cross = options.crossTrigger ?? trigger;
  const rawLeft = side === 'right' ? cross.right + gap : cross.left - gap - boxWidth;
  const left = clamp(rawLeft, edge, viewport.width - boxWidth - edge);
  const desiredTop =
    align === 'start'
      ? trigger.top
      : align === 'end'
        ? trigger.bottom - height
        : trigger.top + trigger.height / 2 - height / 2;
  const top = clamp(desiredTop, edge, viewport.height - height - edge);
  return { side, top, left, maxWidth: available, maxHeight, width: boxWidth, height };
}

export type UseAnchoredPanelOptions = {
  open: boolean;
  /** The `position: relative` box the panel is absolutely positioned in. */
  rootRef: RefObject<HTMLElement | null>;
  /** Element the panel follows when it differs from the offset parent. */
  anchorRef?: RefObject<HTMLElement | null>;
  /** Panel whose outer edge a left/right flyout hangs off (see `crossTrigger`). */
  edgeRef?: RefObject<HTMLElement | null>;
  side?: PopoverSide;
  align?: PopoverAlign;
  gap?: number;
  /**
   * Paint the panel in `document.body` with `position: fixed` instead of inside
   * `rootRef`. Portaled is the default: an in-flow panel is clipped by the
   * first `overflow: auto` ancestor (history scroller, composer tray) and is
   * captured by that ancestor's stacking context, so it can render under a
   * sibling card — both are reported UI bugs, and no per-container `z-index`
   * fixes the whole class.
   */
  portal?: boolean;
  /** Match the anchor's width (composer-wide menus). */
  matchWidth?: boolean;
};

/**
 * Positioner for a popover, portaled to `document.body` by default.
 *
 * Writes `top`/`left`/`max-*` straight to the node during commit instead of
 * storing coordinates in state: the panel is measured, placed, and only then
 * unhidden, so there is no misplaced first paint and no cascading re-render.
 * Every open panel re-measures on resize and on any scroll (capture), which is
 * what keeps it glued to its trigger.
 */
export function useAnchoredPanel({
  open,
  rootRef,
  anchorRef,
  side = 'bottom',
  align = 'start',
  gap = POPOVER_GAP,
  portal = true,
  matchWidth = false,
  edgeRef,
}: UseAnchoredPanelOptions) {
  const nodeRef = useRef<HTMLElement | null>(null);
  const frameRef = useRef(0);

  const place = useCallback(() => {
    const anchor = anchorRef?.current ?? rootRef.current;
    const root = rootRef.current ?? anchor;
    const panel = nodeRef.current;
    if (!root || !anchor || !panel) return;
    const trigger = anchor.getBoundingClientRect();
    const crossTrigger = edgeRef?.current?.getBoundingClientRect() ?? trigger;
    // A portaled panel is measured against the viewport, not its trigger box.
    const rootRect = portal ? { top: 0, left: 0 } : root.getBoundingClientRect();
    const placed = placePopover(
      trigger,
      // `scrollHeight`/`offsetWidth` stay at the natural size even when a
      // previous placement already capped the panel.
      { width: panel.offsetWidth, height: panel.scrollHeight },
      { side, align, gap, matchWidth, crossTrigger }
    );
    if (portal) {
      panel.style.position = 'fixed';
      // Above every app-chrome layer (sidebar drawer 30, scrim 28, modals 120):
      // a menu opened *inside* a dialog is portaled to body, so a lower value
      // would paint it under its own mask.
      panel.style.zIndex = '130';
    }
    panel.style.top = `${placed.top - rootRect.top}px`;
    panel.style.left = `${placed.left - rootRect.left}px`;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.maxWidth = `${placed.maxWidth}px`;
    panel.style.maxHeight = `${placed.maxHeight}px`;
    if (matchWidth) {
      panel.style.width = `${placed.width}px`;
      panel.style.minWidth = '0';
    }
    panel.dataset.side = placed.side;
    panel.style.visibility = '';
  }, [align, anchorRef, edgeRef, gap, matchWidth, portal, rootRef, side]);

  const panelRef = useCallback(
    (node: HTMLElement | null) => {
      nodeRef.current = node;
      if (!node) return;
      // Hidden for the single frame between mount and measurement.
      node.style.visibility = 'hidden';
      place();
    },
    [place]
  );

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const schedule = () => {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(place);
    };
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    // Nested panel swaps (e.g. toolkit → web-search) change height without a
    // window event; without this the fixed `top` stays put and the taller
    // card grows down into the composer («верстка уехала»).
    const panel = nodeRef.current;
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined' && panel) {
      ro = new ResizeObserver(schedule);
      ro.observe(panel);
    }
    return () => {
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
      ro?.disconnect();
    };
  }, [open, place]);

  return panelRef;
}
