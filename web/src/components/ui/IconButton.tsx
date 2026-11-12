import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  /** Visual density — square hit target. */
  size?: 'sm' | 'md' | 'lg';
  /** Filled circular variant (send / stop). */
  tone?: 'ghost' | 'solid' | 'soft';
  /** Explicit: popover triggers need their own node to whitelist the click. */
  ref?: Ref<HTMLButtonElement>;
};

/**
 * Chrome icon control — hover keeps SVG locked (opacity only; no scale).
 */
export function IconButton({
  children,
  className,
  size = 'md',
  tone = 'ghost',
  type = 'button',
  ref,
  ...rest
}: IconButtonProps) {
  const classes = ['icon-btn', `icon-btn--${size}`, `icon-btn--${tone}`, className]
    .filter(Boolean)
    .join(' ');

  return (
    <button ref={ref} type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
