import { Toaster } from 'react-hot-toast';
import { Sparkles } from 'lucide-react';
import { ChatShell } from './components/ChatShell';
import { setPanelOpen } from './runtime/store';
import { useAssistantRuntime } from './runtime/useRuntime';
import { t } from './i18n';

/**
 * Корень виджета: панель + лончер.
 *
 * `ChatShell` НЕ размонтируется при сворачивании (иначе терялась бы история
 * диалога и открытые HITL-карточки) — скрывается через `.is-collapsed`, состояние
 * панели живёт в runtime-store и отражено атрибутом `[collapsed]` на хосте.
 */
export default function App() {
  const { panelOpen } = useAssistantRuntime();

  return (
    <div className={`widget-root${panelOpen ? '' : ' is-collapsed'}`}>
      <ChatShell />
      <button
        type="button"
        className="launcher"
        part="launcher"
        onClick={() => setPanelOpen(true)}
        aria-label={t('launcher.open')}
      >
        <Sparkles size={18} className="brand-mark" aria-hidden />
        {t('launcher.label')}
      </button>
      <Toaster position="bottom-right" toastOptions={{ duration: 3000 }} />
    </div>
  );
}
