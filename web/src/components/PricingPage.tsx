import { IconCheck, IconCrown } from '../icons/kimiStroke';
import { t } from '../i18n';
import type { MessageKey } from '../i18n/messages';

const STANDARD_FEATURES: readonly MessageKey[] = [
  'pricing.feat.chat',
  'pricing.feat.files',
  'pricing.feat.memory',
  'pricing.feat.tools',
];

const PRO_FEATURES: readonly MessageKey[] = [
  'pricing.feat.plugins',
  'pricing.feat.research',
  'pricing.feat.studio',
  'pricing.feat.limits',
];

/**
 * Kimi `/membership` surface.
 *
 * No checkout: entitlement is provisioned by the workspace admin (RBAC/roles),
 * so the page states capabilities and the upgrade path instead of rendering a
 * payment button that cannot complete. Plan copy is explicit about that.
 */
export function PricingPage() {
  return (
    <div className="pricing-page" data-zone="ZONE_BODY">
      <div className="pricing-page__inner">
        <header className="pricing-page__head">
          <span className="pricing-page__eyebrow">
            <IconCrown size={14} />
            <span>{t('upgrade.eyebrow')}</span>
          </span>
          <h1 className="pricing-page__title">{t('upgrade.title')}</h1>
          <p className="pricing-page__subtitle">{t('upgrade.body')}</p>
        </header>

        <div className="pricing-page__plans">
          <section className="pricing-card is-current" aria-label={t('upgrade.standard')}>
            <div className="pricing-card__head">
              <h2 className="pricing-card__name">{t('upgrade.standard')}</h2>
              <span className="pricing-card__badge">{t('upgrade.current')}</span>
            </div>
            <p className="pricing-card__desc">{t('upgrade.standardDesc')}</p>
            <ul className="pricing-card__list">
              {STANDARD_FEATURES.map(key => (
                <li key={key} className="pricing-card__item">
                  <IconCheck size={14} />
                  <span>{t(key)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="pricing-card" aria-label={t('upgrade.pro')}>
            <div className="pricing-card__head">
              <h2 className="pricing-card__name">{t('upgrade.pro')}</h2>
            </div>
            <p className="pricing-card__desc">{t('upgrade.proDesc')}</p>
            <ul className="pricing-card__list">
              {PRO_FEATURES.map(key => (
                <li key={key} className="pricing-card__item">
                  <IconCheck size={14} />
                  <span>{t(key)}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <aside className="pricing-page__note">
          <h3 className="pricing-page__note-title">{t('upgrade.contact')}</h3>
          <p className="pricing-page__note-body">{t('upgrade.contactBody')}</p>
        </aside>
      </div>
    </div>
  );
}
