import { useRef } from 'react';
import { ThinkingOrb, type OrbSize } from 'thinking-orbs';
import { useAppTheme } from '../../lib/theme';

export type AvatarKind = 'assistant' | 'user' | 'thinking';

export type AvatarProps = {
  kind?: AvatarKind;
  /** Диаметр mark/user; thinking мапится на preset библиотеки 20|32|64. */
  size?: number;
  label?: string;
  className?: string;
};

function orbSizeFor(size: number): OrbSize {
  if (size <= 24) return 20;
  if (size <= 40) return 32;
  return 64;
}

/**
 * Аватар ассистента — упрощённая геометрия Logo System (звезда порядка/напряжения).
 * Режим `thinking` — [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs)
 * (`working`, theme из host `data-theme`).
 */
export function Avatar({ kind = 'assistant', size = 28, label, className }: AvatarProps) {
  const rootClass = ['kimi-avatar', `kimi-avatar--${kind}`, className].filter(Boolean).join(' ');
  const anchorRef = useRef<HTMLSpanElement>(null);
  const theme = useAppTheme(anchorRef);

  if (kind === 'thinking') {
    const orbSize = orbSizeFor(size);
    return (
      <span className={rootClass} style={{ width: orbSize, height: orbSize }} ref={anchorRef}>
        <ThinkingOrb state="working" size={orbSize} theme={theme} aria-hidden="true" />
      </span>
    );
  }

  if (kind === 'user') {
    return (
      <span
        className={rootClass}
        style={{ width: size, height: size }}
        aria-hidden={label ? undefined : true}
        aria-label={label}
        role={label ? 'img' : undefined}
      >
        <span className="kimi-avatar__glyph" aria-hidden="true">
          U
        </span>
      </span>
    );
  }

  return (
    <span
      className={rootClass}
      style={{ width: size, height: size }}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
    >
      <svg
        className="kimi-avatar__mark"
        viewBox="0 0 24 24"
        width={Math.round(size * 0.55)}
        height={Math.round(size * 0.55)}
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M12 2.5L14.2 9.1L21 12L14.2 14.9L12 21.5L9.8 14.9L3 12L9.8 9.1L12 2.5Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      </svg>
    </span>
  );
}
