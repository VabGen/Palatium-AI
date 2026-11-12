import type { CSSProperties, ReactNode } from 'react';

export type PluginLogoProps = {
  id: string;
  name: string;
  accent: string;
  size?: number;
};

const tile: CSSProperties = { width: 20, height: 20, flexShrink: 0 };

/**
 * Solid brand tile with a white glyph — how kimi.ai renders file/tool plugins
 * (Word/Excel/PDF …) at 28px inside the 46px card icon.
 */
function BrandTile({ size, fill, children }: { size: number; fill: string; children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      style={{ width: size, height: size, flexShrink: 0, display: 'block' }}
      aria-hidden
    >
      <rect width="24" height="24" rx="6" fill={fill} />
      {children}
    </svg>
  );
}

/** Mini brand marks for the composer plugins menu (kimi.ai uses real logos).
 *  Unknown plugins fall back to a coloured letter tile. */
export function PluginLogo({ id, name, accent, size = 20 }: PluginLogoProps) {
  const box = { width: size, height: size, flexShrink: 0, display: 'block' as const };

  switch (id) {
    case 'pdf':
      return (
        <BrandTile size={size} fill="#e53935">
          <text
            x="12"
            y="15.4"
            textAnchor="middle"
            fontSize="7.2"
            fontWeight="700"
            fill="#fff"
            letterSpacing="0.2"
          >
            PDF
          </text>
        </BrandTile>
      );
    case 'word':
      return (
        <BrandTile size={size} fill="#1e88e5">
          <text x="12" y="16.6" textAnchor="middle" fontSize="13" fontWeight="700" fill="#fff">
            W
          </text>
        </BrandTile>
      );
    case 'excel':
      return (
        <BrandTile size={size} fill="#43a047">
          <text x="12" y="16.6" textAnchor="middle" fontSize="13" fontWeight="700" fill="#fff">
            X
          </text>
        </BrandTile>
      );
    case 'image-gen':
      return (
        <BrandTile size={size} fill="#8e24aa">
          <path d="M12 5.6l1.5 4 4 1.5-4 1.5-1.5 4-1.5-4-4-1.5 4-1.5z" fill="#fff" opacity="0.95" />
        </BrandTile>
      );
    case 'global-finance':
      return (
        <BrandTile size={size} fill="#00897b">
          <rect x="6.4" y="12" width="2.6" height="6" rx="1" fill="#fff" />
          <rect x="10.7" y="8.6" width="2.6" height="9.4" rx="1" fill="#fff" />
          <rect x="15" y="5.4" width="2.6" height="12.6" rx="1" fill="#fff" />
        </BrandTile>
      );
    case 'imf':
      return (
        <BrandTile size={size} fill="#3949ab">
          <circle cx="12" cy="12" r="6.2" fill="none" stroke="#fff" strokeWidth="1.5" />
          <path
            d="M12 5.8c2 1.8 3 3.9 3 6.2s-1 4.4-3 6.2c-2-1.8-3-3.9-3-6.2s1-4.4 3-6.2z"
            fill="none"
            stroke="#fff"
            strokeWidth="1.5"
          />
          <path d="M5.9 12h12.2" stroke="#fff" strokeWidth="1.5" />
        </BrandTile>
      );
    case 'tripo':
      return (
        <BrandTile size={size} fill="#fb8c00">
          <path
            d="M12 5.6l5.6 3.2v6.4L12 18.4l-5.6-3.2V8.8z"
            fill="none"
            stroke="#fff"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M12 12l5.6-3.2M12 12v6.4M12 12L6.4 8.8" stroke="#fff" strokeWidth="1.5" />
        </BrandTile>
      );
    case 'academic':
      return (
        <BrandTile size={size} fill="#5e35b1">
          <path d="M12 6.2l6 2.6-6 2.6-6-2.6z" fill="#fff" />
          <path
            d="M7.6 11v3.6c0 1.4 2 2.4 4.4 2.4s4.4-1 4.4-2.4V11"
            fill="none"
            stroke="#fff"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </BrandTile>
      );
    case 'world-bank':
      return (
        <BrandTile size={size} fill="#039be5">
          <path d="M6 7.4h12l-1.4 3H7.4z" fill="#fff" />
          <rect x="8" y="11.6" width="2" height="5.8" fill="#fff" />
          <rect x="11" y="11.6" width="2" height="5.8" fill="#fff" />
          <rect x="14" y="11.6" width="2" height="5.8" fill="#fff" />
        </BrandTile>
      );
    case 'intl-orgs':
      return (
        <BrandTile size={size} fill="#546e7a">
          <circle cx="12" cy="12" r="6.2" fill="none" stroke="#fff" strokeWidth="1.5" />
          <path d="M5.9 12h12.2" stroke="#fff" strokeWidth="1.5" />
          <path
            d="M12 5.8c1.7 1.9 2.5 4 2.5 6.2s-.8 4.3-2.5 6.2c-1.7-1.9-2.5-4-2.5-6.2s.8-4.3 2.5-6.2z"
            fill="none"
            stroke="#fff"
            strokeWidth="1.2"
          />
        </BrandTile>
      );
    case 'sec':
      return (
        <BrandTile size={size} fill="#1a3c6e">
          <path
            d="M6.4 9.4h11.2M6.4 12h11.2M6.4 14.6h7.4"
            stroke="#fff"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <path
            d="M7 17.6h10"
            stroke="#fff"
            strokeWidth="1.5"
            strokeLinecap="round"
            opacity="0.6"
          />
        </BrandTile>
      );
    case 'gmail':
      return (
        <svg viewBox="0 0 24 24" style={box} aria-hidden>
          <rect
            x="1.5"
            y="3.5"
            width="21"
            height="17"
            rx="3.4"
            fill="#fff"
            stroke="rgb(0 0 0 / 10%)"
          />
          <path
            d="M4.9 17.4V8.3l7.1 5.3 7.1-5.3v9.1"
            fill="none"
            stroke="#EA4335"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case 'drive':
      return (
        <svg viewBox="0 0 24 24" style={box} aria-hidden>
          <path fill="#4285F4" d="M9 3 2 15l3.6 5.5L12.6 8.5z" />
          <path fill="#FBBC04" d="M15 3H9l7 12h6.4z" />
          <path fill="#0F9D58" d="M5.6 20.5h13L22 15H9z" />
        </svg>
      );
    case 'calendar':
      return (
        <svg viewBox="0 0 24 24" style={box} aria-hidden>
          <rect
            x="2.5"
            y="3.5"
            width="19"
            height="17"
            rx="3.4"
            fill="#fff"
            stroke="rgb(0 0 0 / 10%)"
          />
          <path d="M2.5 7.4h19" stroke="#4285F4" strokeWidth="3.4" />
          <text x="12" y="17.6" textAnchor="middle" fontSize="8.4" fontWeight="600" fill="#4285F4">
            31
          </text>
        </svg>
      );
    case 'slack':
      return (
        <svg viewBox="0 0 24 24" style={box} aria-hidden>
          <rect
            x="2.5"
            y="3.5"
            width="19"
            height="17"
            rx="3.4"
            fill="#fff"
            stroke="rgb(0 0 0 / 10%)"
          />
          <rect x="5" y="9.6" width="6.2" height="2.6" rx="1.3" fill="#36C5F0" />
          <rect x="9.9" y="5" width="2.6" height="6.2" rx="1.3" fill="#2EB67D" />
          <rect x="12.8" y="11.8" width="6.2" height="2.6" rx="1.3" fill="#ECB22E" />
          <rect x="11.5" y="12.8" width="2.6" height="6.2" rx="1.3" fill="#E01E5A" />
        </svg>
      );
    case 'figma':
      return (
        <svg viewBox="0 0 24 24" style={box} aria-hidden>
          <path fill="#F24E1E" d="M8.6 3H12v6H8.6a3 3 0 0 1 0-6z" />
          <path fill="#FF7262" d="M12 3h3.4a3 3 0 0 1 0 6H12z" />
          <path fill="#A259FF" d="M8.6 9H12v6H8.6a3 3 0 0 1 0-6z" />
          <circle cx="15.4" cy="12" r="3" fill="#1ABCFE" />
          <path fill="#0ACF83" d="M8.6 15H12v3a3 3 0 1 1-3.4-3z" />
        </svg>
      );
    default:
      return (
        <span
          className="plugin-logo__letter"
          style={{ ...tile, width: size, height: size, background: accent }}
          aria-hidden
        >
          {name.slice(0, 1).toUpperCase()}
        </span>
      );
  }
}
