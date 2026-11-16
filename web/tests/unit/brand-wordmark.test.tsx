import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrandWordmark } from '../../src/components/BrandWordmark';

describe('BrandWordmark doodle', () => {
  it('renders a 400×82 SVG banner with the brand name', () => {
    const { container } = render(<BrandWordmark />);
    const svg = container.querySelector('.brand-doodle__svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('viewBox')).toBe('0 0 400 82');
    expect(screen.getByRole('img', { name: /palatium/i })).toBeTruthy();
    expect(container.querySelector('.brand-doodle__text')?.textContent).toMatch(/palatium/i);
  });
});
