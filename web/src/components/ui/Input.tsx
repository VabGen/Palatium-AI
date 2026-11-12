import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

type Shared = {
  className?: string;
};

/**
 * Текстовый input (Typography & Layout: Inter body, spacing from --space-*).
 */
export function Input({ className, ...rest }: Shared & InputHTMLAttributes<HTMLInputElement>) {
  const classes = ['kimi-input', className].filter(Boolean).join(' ');
  return <input className={classes} {...rest} />;
}

/**
 * Многострочный ввод composer-уровня (field-sizing остаётся на CSS).
 */
export function TextArea({
  className,
  ...rest
}: Shared & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const classes = ['kimi-textarea', className].filter(Boolean).join(' ');
  return <textarea className={classes} {...rest} />;
}
