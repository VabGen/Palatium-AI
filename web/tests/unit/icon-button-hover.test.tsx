import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { IconButton } from '../../src/components/ui/IconButton';
import { IconPlus } from '../../src/icons/kimiStroke';

describe('IconButton hover chrome', () => {
  it('exposes icon-btn class for CSS hover motion', () => {
    const { container } = render(
      <IconButton aria-label="Add">
        <IconPlus size={16} />
      </IconButton>
    );
    const btn = container.querySelector('button');
    expect(btn?.classList.contains('icon-btn')).toBe(true);
    expect(btn?.querySelector('svg')).not.toBeNull();
  });
});
