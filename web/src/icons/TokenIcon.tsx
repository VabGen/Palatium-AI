import { LottieLight } from 'lottie-react';
import type { ComponentType, CSSProperties } from 'react';
import type { IconToken } from '../types/contentDocument';
import { useReducedMotion } from '../lib/motion';
import dangerAnim from '../lottie/danger.json';
import infoAnim from '../lottie/info.json';
import successAnim from '../lottie/success.json';
import warningAnim from '../lottie/warning.json';
import { GlyphInfo, KIMI_TOKEN_GLYPHS, type KimiGlyphProps } from './kimiTokenGlyphs';

const TOKEN_MAP: Record<IconToken, ComponentType<KimiGlyphProps>> = KIMI_TOKEN_GLYPHS;

/**
 * Lottie only for callout/status tones in prose.
 * Action tokens (check/x/clock/shield) stay on official Kimi glyphs — Lottie
 * approximations rendered as white blobs on inverse/primary buttons.
 *
 * | Category | Tokens | Animate |
 * | Status tone | info, success, warning, danger | Lottie when requested |
 * | Content / action | calendar…settings, check, x, clock, shield | static glyph (+ optional CSS pulse) |
 */
const LOTTIE_BY_TOKEN: Partial<Record<IconToken, object>> = {
  info: infoAnim,
  success: successAnim,
  warning: warningAnim,
  danger: dangerAnim,
};

/** Default when LLM invents a name outside the allow-list — never render raw tags. */
const FALLBACK_ICON: ComponentType<KimiGlyphProps> = GlyphInfo;
const FALLBACK_TOKEN: IconToken = 'info';

type TokenIconProps = {
  /** Known IconToken, or raw string from stream (unknown → fallback + warn). */
  token?: IconToken | string | null;
  className?: string;
  size?: number;
  animated?: boolean;
  /** Optional turn correlation for warn logs (Path C). */
  turnId?: string | null;
};

function resolveToken(token: IconToken | string | null | undefined): {
  known: IconToken | null;
  raw: string | null;
} {
  if (token == null || token === '') return { known: null, raw: null };
  const raw = String(token).trim().toLowerCase();
  if (!raw) return { known: null, raw: null };
  // `in` walks the prototype chain: 'constructor' / '__proto__' / 'toString' are
  // "in" any object literal too. Own-property check only.
  if (Object.hasOwn(TOKEN_MAP, raw)) return { known: raw as IconToken, raw };
  return { known: null, raw };
}

export function TokenIcon({
  token,
  className,
  size = 18,
  animated = false,
  turnId = null,
}: TokenIconProps) {
  // Hook before any early return — order must not depend on token resolution.
  const reduceMotion = useReducedMotion();
  const { known, raw } = resolveToken(token);
  if (raw == null && known == null) return null;

  const resolved: IconToken = known ?? FALLBACK_TOKEN;
  if (!known && raw) {
    console.warn('[TokenIcon] unknown icon name; using fallback', {
      name: raw,
      turnId,
      fallback: FALLBACK_TOKEN,
    });
  }

  const lottieData =
    animated && !reduceMotion && Object.hasOwn(LOTTIE_BY_TOKEN, resolved)
      ? LOTTIE_BY_TOKEN[resolved]
      : undefined;
  const sizeStyle = {
    width: size,
    height: size,
    ['--token-icon-size']: `${size}px`,
  } as CSSProperties;

  if (lottieData) {
    return (
      <span
        className={['token-icon', 'token-lottie', className].filter(Boolean).join(' ')}
        style={{ ...sizeStyle, display: 'inline-flex' }}
        aria-hidden
      >
        <LottieLight
          src={lottieData}
          loop={false}
          autoplay={!reduceMotion}
          style={{ width: size, height: size }}
        />
      </span>
    );
  }

  const Icon = TOKEN_MAP[resolved] ?? FALLBACK_ICON;
  return (
    <Icon
      size={size}
      className={['token-icon', className, animated ? 'icon-animated' : '']
        .filter(Boolean)
        .join(' ')}
      style={sizeStyle}
    />
  );
}
