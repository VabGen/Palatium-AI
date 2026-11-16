import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IconCalendar, IconFileText } from '../../src/icons/kimiStroke';
import { CustomizeSidebarDialog } from '../../src/components/CustomizeSidebarDialog';
import { ScheduledTasksPage } from '../../src/components/ScheduledTasksPage';
import { setI18nLocale } from '../../src/i18n';

beforeEach(() => {
  setI18nLocale('en-US');
});

afterEach(() => {
  setI18nLocale('ru-RU');
});

describe('Scheduled tasks page', () => {
  it('renders the 800px task surface with a split create control', () => {
    const { container } = render(<ScheduledTasksPage onCompose={() => undefined} />);
    expect(container.querySelector('.task-page')).not.toBeNull();
    expect(container.querySelector('.task-create-main')).toHaveTextContent('Create');
    expect(screen.getByRole('button', { name: 'Create options' })).toBeTruthy();
    expect(container.querySelector('.task-empty__art')).not.toBeNull();
  });

  it('routes the chat creation path through the composer', () => {
    const onCompose = vi.fn();
    render(<ScheduledTasksPage onCompose={onCompose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create via chat' }));
    expect(onCompose).toHaveBeenCalledTimes(1);
    expect(onCompose.mock.calls[0]?.[0]).toContain('scheduled task');
  });

  it('builds a structured instruction from the manual form', () => {
    const onCompose = vi.fn();
    render(<ScheduledTasksPage onCompose={onCompose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Daily digest' } });
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Summarize new documents' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onCompose).toHaveBeenCalledTimes(1);
    const prompt = String(onCompose.mock.calls[0]?.[0]);
    expect(prompt).toContain('Daily digest');
    expect(prompt).toContain('Summarize new documents');
    expect(prompt).toContain('Daily at');
    expect(prompt).toContain('K3');
  });

  it('requires a name before handing the task to the assistant', () => {
    const onCompose = vi.fn();
    render(<ScheduledTasksPage onCompose={onCompose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onCompose).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a task name');
  });

  it('switches cadence controls between daily, weekly, monthly and once', () => {
    render(<ScheduledTasksPage onCompose={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    fireEvent.click(screen.getByRole('radio', { name: 'Weekly' }));
    expect(document.querySelector('.task-schedule__summary')).toHaveTextContent('Weekly on');

    fireEvent.click(screen.getByRole('radio', { name: 'Monthly' }));
    expect(document.querySelector('.task-schedule__summary')).toHaveTextContent('Monthly on day');

    fireEvent.click(screen.getByRole('radio', { name: 'Once' }));
    expect(document.querySelector('.task-schedule__summary')).toHaveTextContent('Once on');
    expect(screen.getByRole('button', { name: 'Date' })).toBeTruthy();
  });
});

describe('Customize Sidebar dialog', () => {
  const features = [
    { id: 'chats', label: 'Chats', icon: IconCalendar },
    { id: 'docs', label: 'Docs', icon: IconFileText },
  ];

  it('saves the pinned set after a toggle', () => {
    const onSave = vi.fn();
    render(
      <CustomizeSidebarDialog
        features={features}
        value={{ pinned: ['chats', 'docs'], order: ['chats', 'docs'] }}
        onClose={() => undefined}
        onSave={onSave}
      />
    );

    fireEvent.click(screen.getByRole('switch', { name: 'Pin: Docs' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(onSave).toHaveBeenCalledWith({ pinned: ['chats'], order: ['chats', 'docs'] });
  });

  it('closes on Escape without saving', () => {
    const onClose = vi.fn();
    const onSave = vi.fn();
    render(
      <CustomizeSidebarDialog
        features={features}
        value={{ pinned: ['chats'], order: ['chats', 'docs'] }}
        onClose={onClose}
        onSave={onSave}
      />
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});
