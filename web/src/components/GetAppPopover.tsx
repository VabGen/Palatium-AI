import { useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';

import { t } from '../i18n';
import { encodeQr, qrToSvg } from '../lib/qr';

type AppTab = 'mobile' | 'desktop';

/**
 * Платформенная подпись кнопки скачивания — как `.download-button` в kimi.ai:
 * на Windows «Windows download», на macOS/Linux — своя платформа.
 */
function detectDownloadLabel(): string {
  if (typeof navigator === 'undefined') return t('appDialog.download');
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return t('appDialog.downloadWindows');
  if (/Mac OS X|Macintosh/i.test(ua)) return t('appDialog.downloadMac');
  if (/Linux|X11/i.test(ua)) return t('appDialog.downloadLinux');
  return t('appDialog.download');
}

/** Ссылка, которую кодирует QR: текущий адрес приложения (работает в LAN-контуре). */
function appUrl(): string {
  if (typeof window === 'undefined') return 'https://www.palatium.ai/';
  return `${window.location.origin}${window.location.pathname}`;
}

/** kimi.ai `.launcher-img` (182×92, r10): превью десктопного окна. */
function DesktopPreview(): React.ReactElement {
  return (
    <svg
      className="get-app__launcher"
      width="182"
      height="92"
      viewBox="0 0 182 92"
      aria-hidden
      focusable="false"
    >
      <defs>
        <linearGradient id="get-app-sky" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" className="get-app__sky-stop get-app__sky-stop--start" />
          <stop offset="0.55" className="get-app__sky-stop get-app__sky-stop--mid" />
          <stop offset="1" className="get-app__sky-stop get-app__sky-stop--end" />
        </linearGradient>
        <clipPath id="get-app-clip">
          <rect width="182" height="92" rx="10" />
        </clipPath>
      </defs>
      <g clipPath="url(#get-app-clip)">
        <rect width="182" height="92" fill="url(#get-app-sky)" />
        <ellipse className="get-app__glow get-app__glow--top" cx="150" cy="18" rx="46" ry="34" />
        <ellipse className="get-app__glow get-app__glow--bottom" cx="30" cy="82" rx="42" ry="26" />
        <rect className="get-app__window" x="34" y="16" width="114" height="66" rx="9" />
        <path className="get-app__window-bar" d="M34 25a9 9 0 0 1 9-9h96a9 9 0 0 1 9 9v5H34z" />
        <circle className="get-app__window-dot" cx="42" cy="23" r="2" />
        <circle className="get-app__window-dot" cx="49" cy="23" r="2" />
        <circle className="get-app__window-dot" cx="56" cy="23" r="2" />
        <rect
          className="get-app__line get-app__line--strong"
          x="42"
          y="36"
          width="52"
          height="6"
          rx="3"
        />
        <rect className="get-app__line" x="42" y="46" width="74" height="6" rx="3" />
        <rect className="get-app__line" x="42" y="56" width="62" height="6" rx="3" />
        <rect className="get-app__composer" x="42" y="68" width="98" height="10" rx="5" />
        <circle className="get-app__composer-dot" cx="132" cy="73" r="4" />
      </g>
    </svg>
  );
}

export type GetAppPopoverProps = {
  onClose: () => void;
};

/**
 * Поповер «Get App» (kimi.ai `.app-download`, 224×220): сегментированный
 * переключатель Mobile/Desktop + панель. Позиционируется от кнопки в футере
 * сайдбара (справа от неё, нижний край по кнопке) — обёртка в `HistorySidebar`.
 */
export function GetAppPopover({ onClose }: GetAppPopoverProps): React.ReactElement {
  const [tab, setTab] = useState<AppTab>('desktop');
  const panelRef = useRef<HTMLDivElement>(null);

  const qrSrc = useMemo(
    () =>
      `data:image/svg+xml,${encodeURIComponent(qrToSvg(encodeQr(appUrl(), 'M'), { size: 88 }))}`,
    []
  );
  const downloadLabel = useMemo(() => detectDownloadLabel(), []);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (panelRef.current?.contains(target)) return;
      if (target.closest('.history-sidebar__get-app, .kimi-dd__menu--profile')) return;
      onClose();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('pointerdown', handlePointerDown, true);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  return (
    <div
      className="get-app"
      role="dialog"
      aria-label={t('sidebar.getApp')}
      ref={panelRef}
      data-tab={tab}
    >
      <div className="get-app__toggle" role="tablist" aria-label={t('sidebar.getApp')}>
        {(['mobile', 'desktop'] as const).map(value => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            className={`get-app__toggle-item${tab === value ? ' is-active' : ''}`}
            onClick={() => setTab(value)}
          >
            {value === 'mobile' ? t('appDialog.mobileApp') : t('appDialog.desktopApp')}
          </button>
        ))}
      </div>

      {tab === 'mobile' ? (
        <div className="get-app__panel get-app__panel--mobile">
          {/* QR кодирует текущий адрес приложения; картинка собирается локально. */}
          <div className="get-app__qr">
            <img src={qrSrc} width={88} height={88} alt="" />
          </div>
          <p className="get-app__caption">{t('appDialog.scan')}</p>
        </div>
      ) : (
        <div className="get-app__panel get-app__panel--desktop">
          <DesktopPreview />
          <button
            type="button"
            className="get-app__download"
            onClick={() => toast(t('appDialog.unavailable'))}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden focusable="false">
              <path
                fill="currentColor"
                d="M12 3a1 1 0 0 1 1 1v9.6l3.3-3.3a1 1 0 0 1 1.4 1.4l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 1 1 1.4-1.4L11 13.6V4a1 1 0 0 1 1-1Z"
              />
              <path
                fill="currentColor"
                d="M4 15a1 1 0 0 1 1 1v3h14v-3a1 1 0 1 1 2 0v3.5A1.5 1.5 0 0 1 19.5 21h-15A1.5 1.5 0 0 1 3 19.5V16a1 1 0 0 1 1-1Z"
              />
            </svg>
            <span>{downloadLabel}</span>
          </button>
        </div>
      )}
    </div>
  );
}
