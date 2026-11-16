import { t } from '../i18n';

const CASE_META = [
  {
    id: 'silicon',
    titleKey: 'deepResearch.case.silicon' as const,
    accent: 'var(--kimi-brand-blue)',
  },
  {
    id: 'shipping',
    titleKey: 'deepResearch.case.shipping' as const,
    accent: 'var(--kimi-brand-navy)',
  },
  {
    id: 'paper',
    titleKey: 'deepResearch.case.paper' as const,
    accent: 'var(--kimi-brand-blue-soft)',
  },
] as const;

export type FeaturedResearchCasesProps = {
  onSelect?: (title: string) => void;
};

/**
 * Kimi Deep Research «Featured cases» strip under the composer.
 * Gradient thumbs only — no hotlink to kimi CDN assets.
 */
export function FeaturedResearchCases({ onSelect }: FeaturedResearchCasesProps) {
  return (
    <section className="featured-cases" aria-label={t('deepResearch.featured')}>
      <h2 className="featured-cases__heading">{t('deepResearch.featured')}</h2>
      <ul className="featured-cases__grid">
        {CASE_META.map(item => {
          const title = t(item.titleKey);
          return (
            <li key={item.id}>
              <button
                type="button"
                className="featured-cases__card icon-hover"
                onClick={() => onSelect?.(title)}
              >
                <span
                  className="featured-cases__thumb"
                  style={{
                    backgroundImage: `
                      linear-gradient(180deg, transparent 55%, rgb(0 0 0 / 22%)),
                      linear-gradient(145deg, ${item.accent}, var(--bg-soft) 70%)
                    `,
                  }}
                  aria-hidden
                />
                <span className="featured-cases__title">{title}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
