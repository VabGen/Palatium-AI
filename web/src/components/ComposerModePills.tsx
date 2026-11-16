import { IconBrain, IconGlobe, IconSpark } from '../icons/kimiStroke';

export type ComposerMode = 'web_search' | 'deep_think' | 'agent';

export type ComposerModePillsProps = {
  value: ComposerMode | null;
  onChange: (mode: ComposerMode | null) => void;
  labels: {
    webSearch: string;
    deepThink: string;
    agent: string;
    group: string;
  };
};

const MODES: {
  id: ComposerMode;
  Icon: typeof IconGlobe;
  labelKey: keyof ComposerModePillsProps['labels'];
}[] = [
  { id: 'web_search', Icon: IconGlobe, labelKey: 'webSearch' },
  { id: 'deep_think', Icon: IconBrain, labelKey: 'deepThink' },
  { id: 'agent', Icon: IconSpark, labelKey: 'agent' },
];

/**
 * [ZONE_FOOTER] mode pills — UI Upgrade / kimi.ai composer chrome.
 * Toggle off when pressing the active pill (null = plain chat).
 */
export function ComposerModePills({ value, onChange, labels }: ComposerModePillsProps) {
  return (
    <div className="composer-modes" role="group" aria-label={labels.group}>
      {MODES.map(({ id, Icon, labelKey }) => {
        const active = value === id;
        const label = labels[labelKey];
        return (
          <button
            key={id}
            type="button"
            className={`composer-mode-pill${active ? ' is-active' : ''}`}
            aria-pressed={active}
            onClick={() => onChange(active ? null : id)}
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
