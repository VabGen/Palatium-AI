import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TokenIcon } from '../../src/icons/TokenIcon';

describe('TokenIcon', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a known token as svg', () => {
    const { container } = render(<TokenIcon token="document" />);
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('falls back and warns for unknown names', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<TokenIcon token="not_a_real_icon" turnId="turn-1" />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(warn).toHaveBeenCalledWith(
      '[TokenIcon] unknown icon name; using fallback',
      expect.objectContaining({ name: 'not_a_real_icon', turnId: 'turn-1' })
    );
  });

  it('renders nothing when token is empty', () => {
    const { container } = render(<TokenIcon token={null} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});
