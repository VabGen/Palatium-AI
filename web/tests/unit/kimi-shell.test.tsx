import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ComposerModePills } from '../../src/components/ComposerModePills';
import { HistorySidebar } from '../../src/components/HistorySidebar';
import { KimiDropdown } from '../../src/components/ui/KimiDropdown';

describe('K3 Kimi shell chrome', () => {
  it('marks ZONE_NAV on the history sidebar', () => {
    const { container } = render(
      <HistorySidebar
        collapsed={false}
        onToggleCollapsed={() => undefined}
        threads={[{ id: 't1', title: 'Hello' }]}
        projects={[]}
        activeThreadId="t1"
        activeView="chat"
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    expect(container.querySelector('[data-zone="ZONE_NAV"]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Hello' })).toBeTruthy();
    expect(container.querySelector('.history-sidebar__brand')).not.toBeNull();
    expect(container.querySelector('.history-sidebar__tip')).not.toBeNull();
  });

  it('folds desktop sidebar to zero width without an icon rail', () => {
    const { container } = render(
      <HistorySidebar
        collapsed
        onToggleCollapsed={() => undefined}
        threads={[{ id: 't1', title: 'Hello' }]}
        projects={[]}
        activeThreadId="t1"
        activeView="chat"
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    const nav = container.querySelector('.history-sidebar');
    expect(nav?.classList.contains('is-collapsed')).toBe(true);
    expect(nav?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector('.history-sidebar__icon-rail')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Hello' })).toBeNull();
  });

  it('keeps full nav content in off-canvas drawer when hidden', () => {
    const { container } = render(
      <HistorySidebar
        collapsed
        offcanvas
        offcanvasHidden
        onToggleCollapsed={() => undefined}
        threads={[{ id: 't1', title: 'Hello' }]}
        projects={[]}
        activeThreadId="t1"
        activeView="chat"
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    const nav = container.querySelector('.history-sidebar');
    expect(nav?.classList.contains('is-offcanvas-mode')).toBe(true);
    expect(nav?.classList.contains('is-offcanvas')).toBe(true);
    expect(nav?.classList.contains('is-collapsed')).toBe(false);
    expect(screen.getByRole('button', { name: 'Hello', hidden: true })).toBeTruthy();
  });

  it('toggles project filter via clickable project rows', () => {
    const onSelectProject = vi.fn();
    render(
      <HistorySidebar
        collapsed={false}
        onToggleCollapsed={() => undefined}
        threads={[{ id: 't1', title: 'Hello', projectId: 'p1' }]}
        projects={[{ id: 'p1', title: 'Alpha' }]}
        activeThreadId="t1"
        activeView="chat"
        activeProjectId={null}
        onSelectProject={onSelectProject}
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Alpha/i }));
    expect(onSelectProject).toHaveBeenCalledWith('p1');
  });

  it('calls rename / delete thread handlers from the shelf menu', async () => {
    const onRenameThread = vi.fn();
    const onDeleteThread = vi.fn();
    const { container } = render(
      <HistorySidebar
        collapsed={false}
        onToggleCollapsed={() => undefined}
        threads={[{ id: 't1', title: 'Hello' }]}
        projects={[]}
        activeThreadId="t1"
        activeView="chat"
        onRenameThread={onRenameThread}
        onDeleteThread={onDeleteThread}
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    const threadMore = container.querySelector(
      '.history-sidebar__thread-more'
    ) as HTMLButtonElement | null;
    expect(threadMore).not.toBeNull();
    fireEvent.click(threadMore!);
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    expect(onRenameThread).toHaveBeenCalledWith('t1');
    fireEvent.click(threadMore!);
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    expect(onDeleteThread).toHaveBeenCalledWith('t1');
  });

  it('shows New / Beta badges on product rail items under More', () => {
    const { container } = render(
      <HistorySidebar
        collapsed={false}
        onToggleCollapsed={() => undefined}
        threads={[]}
        projects={[]}
        activeThreadId="t1"
        activeView="chat"
        onSelectThread={() => undefined}
        onNewChat={() => undefined}
        onNavigate={() => undefined}
        userName="Ada"
        labels={{
          nav: 'History',
          newChat: 'New',
          newChatHint: 'Ctrl K',
          collapse: 'Collapse',
          expand: 'Expand',
          history: 'Recent',
          projects: 'Projects',
          createProject: 'New project',
          projectTitleHint: 'Project title',
          renameProject: 'Edit project name',
          pinProject: 'Pin to top',
          deleteProject: 'Delete',
          pin: 'Pin',
          unpin: 'Unpin',
          pinnedSection: 'Pinned',
          profile: 'Profile',
          settings: 'Settings',
          themeHint: 'Theme',
          rename: 'Rename',
          delete: 'Delete',
          allChats: 'All chats',
        }}
      />
    );
    // Product cut dropped 3D Make / Design (New/Beta badges); More keeps Slides only.
    fireEvent.click(screen.getByRole('button', { name: /More|Ещё/i }));
    expect(screen.getByRole('button', { name: /Slides|Слайды/i })).toBeTruthy();
    expect(container.querySelector('.history-sidebar__rail-badge.is-new')).toBeNull();
    expect(container.querySelector('.history-sidebar__rail-badge.is-beta')).toBeNull();
  });

  it('toggles composer mode pills', () => {
    const onChange = vi.fn();
    render(
      <ComposerModePills
        value={null}
        onChange={onChange}
        labels={{
          group: 'Modes',
          webSearch: 'Web Search',
          deepThink: 'Deep Think',
          agent: 'Agent',
        }}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Web Search' }));
    expect(onChange).toHaveBeenCalledWith('web_search');
  });

  it('opens model dropdown with elevated menu', () => {
    const onChange = vi.fn();
    render(
      <KimiDropdown
        label="Model"
        value="k2"
        options={[
          { id: 'k2', label: 'Kimi K2' },
          { id: 'k2-think', label: 'Kimi K2 Thinking' },
        ]}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Model' }));
    // The menu is portaled to `document.body` so no scroller/stacking ancestor clips it.
    expect(screen.getByRole('listbox', { name: 'Model' })).not.toBeNull();
    fireEvent.click(screen.getByRole('option', { name: /Kimi K2 Thinking/i }));
    expect(onChange).toHaveBeenCalledWith('k2-think');
  });
});
