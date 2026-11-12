import { describe, expect, it } from 'vitest';

import { isRecommendationChrome } from '../../src/lib/recommendations';

describe('recommendations chrome', () => {
  it('keys off IconToken check, not heading text', () => {
    expect(isRecommendationChrome('check')).toBe(true);
    expect(isRecommendationChrome('warning')).toBe(false);
    expect(isRecommendationChrome(null)).toBe(false);
    expect(isRecommendationChrome(undefined)).toBe(false);
  });
});
