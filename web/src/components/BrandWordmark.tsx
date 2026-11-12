import { t } from '../i18n';

export type BrandWordmarkProps = {
  className?: string;
};

/**
 * [ZONE_HERO] Home doodle banner — same 400×81 slot as kimi.ai `.home-banner`
 * / `.single-doodle` (measured 400×82 CSS, natural 800×160). Typography & Layout
 * display type + Logo System geometry as an original SVG (not a kimi CDN asset).
 * Living motion stays on `.composer-hero__live` (transform/opacity only).
 */
export function BrandWordmark({ className }: BrandWordmarkProps) {
  const name = t('brand.name');
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
        {/* Soft brand accent under the baseline — Color System signature blue. */}
        <path
          className="brand-doodle__stroke"
          d="M48 66 C120 72 200 58 280 64 C320 67 360 70 372 62"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          opacity="0.35"
        />
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
