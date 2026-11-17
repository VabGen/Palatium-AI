import { useId } from 'react';
import { t } from '../i18n';

export type BrandWordmarkProps = {
  className?: string;
};

/**
 * Organic asymmetric doodle under PALATIUM (reference screenshot 2026-11-16).
 * Not a tiled sine — uneven peaks: low under PA → crest AL → wide trough AT →
 * smaller crest IU → soft exit under M.
 */
const WAVE_A =
  'M48 70 C78 74 108 61 148 63 C178 65 205 73 236 71 C270 69 298 58 332 64 C350 67 362 70 374 65';

/** Sibling shape for crossfade — same topology, shifted accents (alive, not scrolling). */
const WAVE_B =
  'M48 69 C82 72 112 58 150 64 C182 68 208 74 238 70 C272 65 302 56 334 65 C352 69 362 71 374 66';

/**
 * [ZONE_HERO] Home doodle — Typography display + Color System soft blue.
 * Text fixed. Asymmetric stroke + edge dissolve; motion = opacity crossfade
 * between two organic paths (GPU opacity only, 084).
 */
export function BrandWordmark({ className }: BrandWordmarkProps) {
  const name = t('brand.name');
  const uid = useId().replace(/:/g, '');
  const fadeId = `brand-wave-fade-${uid}`;
  const maskId = `brand-wave-mask-${uid}`;

  return (
    <h1
      className={`empty-wordmark composer-home-wordmark brand-doodle${className ? ` ${className}` : ''}`}
    >
      <svg
        className="brand-doodle__svg"
        viewBox="0 0 400 82"
        width="400"
        height="82"
        role="img"
        aria-label={name}
      >
        <defs>
          <linearGradient id={fadeId} x1="40" y1="0" x2="370" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.1" stopColor="#fff" stopOpacity="1" />
            <stop offset="0.9" stopColor="#fff" stopOpacity="1" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="82">
            <rect x="40" y="56" width="330" height="22" fill={`url(#${fadeId})`} />
          </mask>
        </defs>

        <g className="brand-doodle__wave" mask={`url(#${maskId})`} aria-hidden="true">
          <path
            className="brand-doodle__stroke brand-doodle__stroke--a"
            d={WAVE_A}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            className="brand-doodle__stroke brand-doodle__stroke--b"
            d={WAVE_B}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>

        <text
          className="brand-doodle__text"
          x="200"
          y="54"
          textAnchor="middle"
          dominantBaseline="alphabetic"
        >
          {name}
        </text>
      </svg>
    </h1>
  );
}
