import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AnswerFileCards } from '../../src/components/AnswerFileCards';
import { t } from '../../src/i18n';

describe('AnswerFileCards', () => {
  it('renders artifact + all-files cards like kimi under-answer pills', () => {
    const onOpenArtifact = vi.fn();
    const onOpenAllFiles = vi.fn();
    render(
      <AnswerFileCards
        artifactTitle="Tesla tear sheet"
        onOpenArtifact={onOpenArtifact}
        showAllFiles
        onOpenAllFiles={onOpenAllFiles}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: t('artifact.open') }));
    expect(onOpenArtifact).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: t('attach.allFiles') }));
    expect(onOpenAllFiles).toHaveBeenCalledOnce();
    expect(screen.getAllByText(t('artifact.preview'))).toHaveLength(2);
    expect(screen.getByText(t('attach.allFilesDesc'))).toBeInTheDocument();
  });

  it('shows artifact + cited primary file + all-files like kimi dual pills', () => {
    const onOpenPrimary = vi.fn();
    const onOpenArtifact = vi.fn();
    render(
      <AnswerFileCards
        artifactTitle="Report"
        onOpenArtifact={onOpenArtifact}
        primaryFile={{ id: 'a1', filename: 'tesla_tsla_tear_sheet.pdf' }}
        onOpenPrimary={onOpenPrimary}
        showAllFiles
        onOpenAllFiles={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: t('artifact.open') })).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', {
        name: t('attach.openFile', { name: 'tesla_tsla_tear_sheet.pdf' }),
      })
    );
    expect(onOpenPrimary).toHaveBeenCalledWith('a1', 'tesla_tsla_tear_sheet.pdf');
    expect(screen.getByText('PDF')).toBeInTheDocument();
    expect(screen.getAllByText(t('artifact.preview'))).toHaveLength(3);
  });
});
