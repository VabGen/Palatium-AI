import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'ghost' | 'toolbar' | 'icon';
export type ButtonSize = 'sm' | 'md';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
  /** Shadow DOM CSS part (виджет). */
  part?: string;
};

/**
 * Примитив кнопки (UI Upgrade + Color System).
 * Варианты через токены; без сырого hex.
 */
export function Button({
  variant = 'ghost',
  size = 'md',
  className,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  const classes = ['kimi-btn', `kimi-btn--${variant}`, `kimi-btn--${size}`, className]
    .filter(Boolean)
    .join(' ');

  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
