import type { ShowcaseCard } from '../mocks/productShowcases';

/**
 * Kimi waterfall thumbs: a dark foot for legibility + the card's accent
 * gradient. Shared by the shelf card and its detail modal preview.
 */
export function showcaseThumbStyle(card: ShowcaseCard): { backgroundImage: string } {
  return {
    backgroundImage: `linear-gradient(180deg, transparent 55%, rgb(0 0 0 / 22%)),
      linear-gradient(145deg, ${card.accent}, ${card.accent2} 72%)`,
  };
}

/** Read `?item=<id>` from the current hash (`#/make3d?item=cologne`). */
export function showcaseItemFromHash(hash: string): string | null {
  const query = hash.split('?')[1];
  if (!query) return null;
  return new URLSearchParams(query).get('item');
}
