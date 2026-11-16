import { describe, expect, it } from 'vitest';

import {
  SHELL_COMPACT_MAX_PX,
  SHELL_NARROW_MAX_PX,
  shellDensityFromWidth,
} from '../../src/lib/shellDensity';

describe('shellDensityFromWidth', () => {
  it('marks SED-sized panels as compact and narrow', () => {
    expect(shellDensityFromWidth(400)).toEqual({ narrow: true, compact: true });
    expect(shellDensityFromWidth(SHELL_COMPACT_MAX_PX)).toEqual({
      narrow: true,
      compact: true,
    });
  });

  it('is narrow but comfortable between compact and desktop', () => {
    expect(shellDensityFromWidth(900)).toEqual({ narrow: true, compact: false });
    expect(shellDensityFromWidth(SHELL_NARROW_MAX_PX)).toEqual({
      narrow: true,
      compact: false,
    });
  });

  it('is comfortable on wide shells', () => {
    expect(shellDensityFromWidth(SHELL_NARROW_MAX_PX + 1)).toEqual({
      narrow: false,
      compact: false,
    });
  });
});
