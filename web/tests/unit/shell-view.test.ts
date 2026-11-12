import { describe, expect, it } from 'vitest';
import {
  hashForProject,
  hashForProjectCreate,
  hashForShellView,
  isShellView,
  projectIdFromHash,
  shellViewFromHash,
} from '../../src/lib/shellView';

describe('shellView', () => {
  it('parses hash routes', () => {
    expect(shellViewFromHash('#/plugins')).toBe('plugins');
    expect(shellViewFromHash('#/skills')).toBe('skills');
    expect(shellViewFromHash('#/deep-research')).toBe('deep-research');
    expect(shellViewFromHash('#/inspiration')).toBe('chat');
    expect(shellViewFromHash('#/inspiration/pool')).toBe('chat');
    expect(shellViewFromHash('#/project/create')).toBe('project-create');
    expect(shellViewFromHash('#/project/abc-123')).toBe('project');
    expect(shellViewFromHash('#/make3d')).toBe('chat');
    expect(shellViewFromHash('#/build')).toBe('chat');
    expect(shellViewFromHash('#/design')).toBe('chat');
    expect(shellViewFromHash('#/work')).toBe('chat');
    expect(shellViewFromHash('#/code')).toBe('chat');
    expect(shellViewFromHash('#/platform')).toBe('chat');
    expect(shellViewFromHash('#/')).toBe('chat');
    expect(shellViewFromHash('')).toBe('chat');
  });

  it('round-trips hash helpers', () => {
    expect(hashForShellView('plugins')).toBe('#/plugins');
    expect(hashForShellView('deep-research')).toBe('#/deep-research');
    expect(hashForShellView('project-create')).toBe('#/project/create');
    expect(hashForProjectCreate()).toBe('#/project/create');
    expect(hashForProject('abc-123')).toBe('#/project/abc-123');
    expect(projectIdFromHash('#/project/abc-123')).toBe('abc-123');
    expect(projectIdFromHash('#/project/create')).toBe(null);
    expect(isShellView('skills')).toBe(true);
    expect(isShellView('deep-research')).toBe(true);
    expect(isShellView('inspiration')).toBe(false);
    expect(isShellView('project-create')).toBe(true);
    expect(isShellView('billing')).toBe(false);
  });
});
