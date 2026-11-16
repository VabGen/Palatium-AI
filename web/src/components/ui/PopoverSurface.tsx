import {
  useCallback,
  useEffect,
  useRef,
  type MouseEvent as ReactMouseEvent,
  type MutableRefObject,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { useAnchoredPanel, type PopoverAlign, type PopoverSide } from './useAnchoredPopover';

export type PopoverSurfaceProps = {
  open: boolean;
  /** Trigger box the panel is anchored to. */
  rootRef: RefObject<HTMLElement | null>;
  /** Anchor override (a row inside the panel, a sibling trigger). */
  anchorRef?: RefObject<HTMLElement | null>;
  /** Panel whose outer edge a left/right flyout hangs off. */
  edgeRef?: RefObject<HTMLElement | null>;
  side?: PopoverSide;
  align?: PopoverAlign;
  gap?: number;
  /** Match the anchor's width (composer-wide menus). */
  matchWidth?: boolean;
  id?: string;
  className: string;
  role: 'menu' | 'listbox';
  label?: string;
  /** Tag of the surface — `ul` for `listbox`, `div` for `menu`. */
  as?: 'div' | 'ul';
  /** Exposes the mounted surface so a sibling flyout can whitelist its clicks. */
  nodeRef?: MutableRefObject<HTMLElement | null>;
  /** Sibling panels whose clicks must not dismiss this one (flyout pairs). */
  keepOpenRefs?: readonly RefObject<HTMLElement | null>[];
  onDismiss: () => void;
  /** Escape hook when it differs from a plain dismiss (e.g. close a subform). */
  onEscape?: () => void;
  /** Hover handoff for flyouts: the parent row and the panel keep each other open. */
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
  /** Panel-level click (e.g. close a menu once one of its items is activated). */
  onClick?: (event: ReactMouseEvent<HTMLElement>) => void;
  children: ReactNode;
};

/**
 * Anchored popover surface rendered into `document.body`.
 *
 * Portaling is what makes the placement contract hold everywhere: a panel in
 * flow is clipped by the first `overflow: auto` ancestor and is captured by
 * that ancestor's stacking context, so it can appear cut off at the viewport
 * edge or painted under a sibling card. In `body` the only constraints left are
 * the viewport itself, which `placePopover` already clamps.
 */
export function PopoverSurface({
  open,
  rootRef,
  anchorRef,
  edgeRef,
  side = 'bottom',
  align = 'start',
  gap,
  matchWidth,
  id,
  className,
  role,
  label,
  as = 'div',
  nodeRef: externalNodeRef,
  keepOpenRefs,
  onDismiss,
  onEscape,
  onPointerEnter,
  onPointerLeave,
  onClick,
  children,
}: PopoverSurfaceProps) {
  const nodeRef = useRef<HTMLElement | null>(null);
  const panelRef = useAnchoredPanel({
    open,
    rootRef,
    anchorRef,
    edgeRef,
    side,
    align,
    gap,
    matchWidth,
  });

  const attach = useCallback(
    (node: HTMLElement | null) => {
      nodeRef.current = node;
      if (externalNodeRef) externalNodeRef.current = node;
      if (node) {
        // Pre-measurement frame: pinned at the origin and unpainted, so a
        // fixed panel cannot widen the page before placement runs.
        node.style.position = 'fixed';
        node.style.top = '0px';
        node.style.left = '0px';
        node.style.visibility = 'hidden';
        node.style.maxWidth = '100vw';
      }
      panelRef(node);
    },
    [externalNodeRef, panelRef]
  );

  useEffect(() => {
    if (!open) return;
    const isInside = (node: Node) => {
      if (nodeRef.current?.contains(node)) return true;
      if (rootRef.current?.contains(node)) return true;
      return (keepOpenRefs ?? []).some(ref => ref.current?.contains(node));
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!isInside(event.target as Node)) onDismiss();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (onEscape) onEscape();
      else onDismiss();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [keepOpenRefs, onDismiss, onEscape, open, rootRef]);

  if (!open) return null;

  const Surface = as;
  return createPortal(
    <Surface
      id={id}
      ref={attach}
      className={className}
      role={role}
      aria-label={label}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      onClick={onClick}
    >
      {children}
    </Surface>,
    document.body
  );
}
