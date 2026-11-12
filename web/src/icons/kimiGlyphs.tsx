import type { SVGProps } from 'react';

/**
 * Filled glyphs from the kimi.ai bundle (1024 grid). Kimi uses these for
 * action pills, carousel arrows and modal chrome — a different family from the
 * stroke icons in `kimiStroke.tsx`, so they live here verbatim.
 */
export type KimiGlyphProps = SVGProps<SVGSVGElement> & { size?: number };

function glyph(size: number): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 1024 1024',
    fill: 'currentColor',
    'aria-hidden': true,
    focusable: false,
  };
}

/** `.inspiration-card-action-button` remix glyph. */
export function IconGlyphRemix({ size = 18, ...rest }: KimiGlyphProps) {
  return (
    <svg {...glyph(size)} {...rest}>
      <path d="M819.029333 400.128a123.733333 123.733333 0 0 1 87.509334 151.552l-66.218667 247.296a123.776 123.776 0 0 1-151.594667 87.466667l-209.493333-56.149334 131.925333-35.328c4.992-1.365333 9.813333-3.072 14.506667-4.949333l82.986667 22.229333a46.933333 46.933333 0 0 0 57.429333-33.152l66.261333-247.296a46.933333 46.933333 0 0 0-33.152-57.472l-157.056-42.069333-22.954666-85.717333 199.850666 53.589333z" />
      <path d="M434.304 281.6a123.776 123.776 0 0 1 151.552 87.509333l66.218667 247.296A123.733333 123.733333 0 0 1 564.608 768l-247.296 66.304A123.776 123.776 0 0 1 165.76 746.666667l-66.261333-247.253334a123.776 123.776 0 0 1 87.509333-151.594666l247.296-66.218667z m77.312 107.434667a46.933333 46.933333 0 0 0-57.429333-33.194667L206.890667 422.144a46.933333 46.933333 0 0 0-33.194667 57.429333l66.261333 247.253334a46.933333 46.933333 0 0 0 57.472 33.152l247.296-66.218667a46.933333 46.933333 0 0 0 33.152-57.472l-66.261333-247.253333z" />
      <path d="M640 150.613333c68.352 0 123.733333 55.466667 123.733333 123.733334v70.912l-76.8-20.608V274.389333a46.933333 46.933333 0 0 0-46.933333-46.933333H384c-23.722667 0-43.264 17.578667-46.421333 40.405333L260.266667 288.597333V274.346667A123.776 123.776 0 0 1 384 150.570667h256z" />
    </svg>
  );
}

/** `.carousel-container` arrow chevron (points left before the right rotation). */
export function IconGlyphChevronLeft({ size = 20, ...rest }: KimiGlyphProps) {
  return (
    <svg {...glyph(size)} {...rest}>
      <path d="M342.99904 549.23264a36.864 36.864 0 0 1 0.08192-52.0192l285.696-285.696a36.864 36.864 0 1 1 52.14208 52.10112l-259.6864 259.72736 259.76832 261.69344a36.864 36.864 0 0 1-52.30592 51.93728L342.99904 549.2736z" />
    </svg>
  );
}

/** `.inspiration-detail-close` glyph. */
export function IconGlyphClose({ size = 18, ...rest }: KimiGlyphProps) {
  return (
    <svg {...glyph(size)} {...rest}>
      <path d="M766.037333 203.648a38.4 38.4 0 0 1 54.357334 54.314667L566.314667 512l254.08 254.037333a38.4 38.4 0 0 1-54.357334 54.357334L512 566.314667l-254.037333 254.08a38.4 38.4 0 0 1-54.314667-54.357334L457.685333 512 203.648 257.962667a38.4 38.4 0 0 1 54.314667-54.314667L512 457.685333l254.037333-254.037333z" />
    </svg>
  );
}
