export type PluginCategory =
  | 'installed'
  | 'featured'
  | 'finance'
  | 'productivity'
  | 'creative'
  | 'threeD'
  | 'developer'
  | 'research'
  | 'legal';

export type PluginItem = {
  id: string;
  name: string;
  description: string;
  category: PluginCategory;
  installed: boolean;
  accent: string;
};

/** Order shown in the composer «Плагины» menu (kimi.ai parity). */
export const RECOMMENDED_PLUGIN_IDS = ['gmail', 'drive', 'calendar', 'slack', 'figma'];

/**
 * Tool rows of the composer `+` toolkit menu, in kimi.ai order
 * (`.toolkit-panel`: PDF, Excel, Word, Tripo, Image Generation, then the data
 * providers). Connector plugins (Gmail/Drive…) live in the tray popover only.
 */
export const TOOLKIT_PLUGIN_IDS = [
  'pdf',
  'excel',
  'word',
  'tripo',
  'image-gen',
  'academic',
  'global-finance',
  'world-bank',
  'imf',
  'intl-orgs',
  'sec',
];

/** kimi.ai `/plugins` section rail, in its live order (Installed → Legal). */
export const PLUGIN_CATEGORIES: { id: PluginCategory; labelKey: string }[] = [
  { id: 'installed', labelKey: 'plugins.cat.installed' },
  { id: 'featured', labelKey: 'plugins.cat.featured' },
  { id: 'finance', labelKey: 'plugins.cat.finance' },
  { id: 'productivity', labelKey: 'plugins.cat.productivity' },
  { id: 'creative', labelKey: 'plugins.cat.creative' },
  { id: 'threeD', labelKey: 'plugins.cat.threeD' },
  { id: 'developer', labelKey: 'plugins.cat.developer' },
  { id: 'research', labelKey: 'plugins.cat.research' },
  { id: 'legal', labelKey: 'plugins.cat.legal' },
];

/** Featured shelf is curated, not every non-installed plugin (live `/plugins`). */
export const FEATURED_PLUGIN_IDS = [
  'gmail',
  'calendar',
  'drive',
  'outlook',
  'teams',
  'figma',
  'slack',
  'notion',
  'github',
  'email',
];

/** Cards visible before the "View …" overflow row (2 × 5 grid on 800px). */
export const PLUGIN_SECTION_VISIBLE = 10;

/** Mock marketplace — UI only until backend lands. */
export const PLUGINS_CATALOG: PluginItem[] = [
  {
    id: 'pdf',
    name: 'PDF',
    description: 'PDF document tool',
    category: 'productivity',
    installed: true,
    accent: '#e53935',
  },
  {
    id: 'excel',
    name: 'Excel',
    description: 'Advanced spreadsheet work',
    category: 'productivity',
    installed: true,
    accent: '#43a047',
  },
  {
    id: 'word',
    name: 'Word',
    description: 'Word editing tool',
    category: 'productivity',
    installed: true,
    accent: '#1e88e5',
  },
  {
    id: 'tripo',
    name: 'Tripo 3D generation',
    description: 'Powered by Tripo',
    category: 'threeD',
    installed: true,
    accent: '#fb8c00',
  },
  {
    id: 'image-gen',
    name: 'Image Generation',
    description: 'Generate images from text',
    category: 'creative',
    installed: true,
    accent: '#8e24aa',
  },
  {
    id: 'academic',
    name: 'Academic Data',
    description: 'Academic data search',
    category: 'research',
    installed: true,
    accent: '#5e35b1',
  },
  {
    id: 'global-finance',
    name: 'Global Finance Data',
    description: 'Search global finance data',
    category: 'finance',
    installed: true,
    accent: '#00897b',
  },
  {
    id: 'world-bank',
    name: 'World Bank Open Data',
    description: 'Search World Bank open data',
    category: 'finance',
    installed: true,
    accent: '#039be5',
  },
  {
    id: 'imf',
    name: 'IMF International Monetary Fund Data',
    description: 'Covers global financial data',
    category: 'finance',
    installed: true,
    accent: '#3949ab',
  },
  {
    id: 'intl-orgs',
    name: 'International Organizations Data',
    description: 'Global data sources',
    category: 'finance',
    installed: true,
    accent: '#546e7a',
  },
  {
    id: 'institutional-finance',
    name: 'Institutional Finance Kit',
    description: 'Pro finance agents',
    category: 'finance',
    installed: false,
    accent: '#0b3d91',
  },
  {
    id: 'sp-global',
    name: 'S&P Global Market Intelligence',
    description: 'Fundamental data, estimates and transcripts',
    category: 'finance',
    installed: false,
    accent: '#d32f2f',
  },
  {
    id: 'wind',
    name: 'Wind Financial Data Services',
    description: 'Direct Wind access',
    category: 'finance',
    installed: false,
    accent: '#f57c00',
  },
  {
    id: 'cls-news',
    name: 'CLS News',
    description: 'Real-time financial news',
    category: 'finance',
    installed: false,
    accent: '#c62828',
  },
  {
    id: 'caixin',
    name: 'Caixin Data',
    description: 'Caixin Data Platform',
    category: 'finance',
    installed: false,
    accent: '#1565c0',
  },
  {
    id: 'sec',
    name: 'SEC',
    description: 'US company filings',
    category: 'finance',
    installed: true,
    accent: '#1a3c6e',
  },
  {
    id: 'gmail',
    name: 'Gmail',
    description: 'Gmail management tool',
    category: 'productivity',
    installed: false,
    accent: '#ea4335',
  },
  {
    id: 'email',
    name: 'Email',
    description: 'Email tool for connecting multiple mailboxes',
    category: 'productivity',
    installed: false,
    accent: '#5f6368',
  },
  {
    id: 'calendar',
    name: 'Google Calendar',
    description: 'Google Calendar tool',
    category: 'productivity',
    installed: false,
    accent: '#4285f4',
  },
  {
    id: 'drive',
    name: 'Google Drive',
    description: 'Google Drive tool',
    category: 'productivity',
    installed: false,
    accent: '#34a853',
  },
  {
    id: 'outlook',
    name: 'Outlook',
    description: 'Outlook mail tools',
    category: 'productivity',
    installed: false,
    accent: '#0f6cbd',
  },
  {
    id: 'teams',
    name: 'Microsoft Teams',
    description: 'Teams collaboration',
    category: 'productivity',
    installed: false,
    accent: '#6264a7',
  },
  {
    id: 'notion',
    name: 'Notion',
    description: 'Notion workspace',
    category: 'productivity',
    installed: false,
    accent: '#111111',
  },
  {
    id: 'slack',
    name: 'Slack',
    description: 'Connect Slack teams',
    category: 'productivity',
    installed: false,
    accent: '#611f69',
  },
  {
    id: 'figma',
    name: 'Figma',
    description: 'Figma design tools',
    category: 'creative',
    installed: false,
    accent: '#a259ff',
  },
  {
    id: 'canva',
    name: 'Canva',
    description: 'Canva design tools',
    category: 'creative',
    installed: false,
    accent: '#00c4cc',
  },
  {
    id: 'video-gen',
    name: 'Video Generation',
    description: 'Generate videos from text',
    category: 'creative',
    installed: false,
    accent: '#d81b60',
  },
  {
    id: 'audio-gen',
    name: 'Audio Generation',
    description: 'Generate audio from text',
    category: 'creative',
    installed: false,
    accent: '#00796b',
  },
  {
    id: 'tripo-ai',
    name: 'Tripo AI',
    description: 'Text or image to 3D',
    category: 'threeD',
    installed: false,
    accent: '#f57c00',
  },
  {
    id: 'github',
    name: 'GitHub',
    description: 'Code hosting and developer collaboration',
    category: 'developer',
    installed: false,
    accent: '#24292f',
  },
  {
    id: 'cloudflare',
    name: 'Cloudflare',
    description: 'Network, security, and application deployment',
    category: 'developer',
    installed: false,
    accent: '#f38020',
  },
  {
    id: 'supabase',
    name: 'Supabase',
    description: 'Open-source backend and database platform',
    category: 'developer',
    installed: false,
    accent: '#3ecf8e',
  },
  {
    id: 'neon',
    name: 'Neon',
    description: 'Serverless Postgres database platform',
    category: 'developer',
    installed: false,
    accent: '#00e599',
  },
  {
    id: 'context7',
    name: 'Context7',
    description: 'Context7 doc lookup',
    category: 'developer',
    installed: false,
    accent: '#1a1a1a',
  },
  {
    id: 'pubmed',
    name: 'PubMed & PMC',
    description: 'PubMed & PMC search',
    category: 'research',
    installed: false,
    accent: '#2a6ebb',
  },
  {
    id: 'biorxiv',
    name: 'bioRxiv Preprints',
    description: 'Preprint search',
    category: 'research',
    installed: false,
    accent: '#c62828',
  },
  {
    id: 'uniprot',
    name: 'UniProt',
    description: 'UniProt protein DB',
    category: 'research',
    installed: false,
    accent: '#00539b',
  },
  {
    id: 'legal-assistant',
    name: 'Legal Assistant',
    description: 'China Law Assistant',
    category: 'legal',
    installed: false,
    accent: '#8d6e63',
  },
  {
    id: 'pkulaw',
    name: 'PKULaw',
    description: 'Smart legal search',
    category: 'legal',
    installed: false,
    accent: '#b71c1c',
  },
  {
    id: 'wolters-kluwer',
    name: 'Wolters Kluwer',
    description: 'Legal research',
    category: 'legal',
    installed: false,
    accent: '#0d47a1',
  },
];
