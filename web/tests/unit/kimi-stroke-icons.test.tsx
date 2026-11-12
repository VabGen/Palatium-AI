import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { IconArrowUp, IconPaperclip, IconPlus, IconSpark } from '../../src/icons/kimiStroke';

describe('K5 kimiStroke chrome icons', () => {
  it('uses 1.5px stroke and currentColor', () => {
    const { container } = render(
      <>
        <IconPlus size={18} />
        <IconPaperclip size={15} />
        <IconArrowUp size={18} />
        <IconSpark size={18} />
      </>
    );
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBe(4);
    for (const svg of svgs) {
      expect(svg.getAttribute('stroke-width')).toBe('1.5');
      expect(svg.getAttribute('stroke')).toBe('currentColor');
      expect(svg.getAttribute('fill')).toBe('none');
    }
  });
});
