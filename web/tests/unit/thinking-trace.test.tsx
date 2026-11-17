import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ThinkingTrace } from '../../src/components/MessageChrome';

describe('ThinkingTrace', () => {
  it('hides completed chrome when there is no detail to expand', () => {
    const { container } = render(<ThinkingTrace phaseLabel="Thinking" detail={null} complete />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders when there is expandable detail', () => {
    render(<ThinkingTrace phaseLabel="Thinking" detail="Шаг 1: поиск" complete />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});
