/**
 * Kimi product-landing template shelves.
 *
 * Content mirrors kimi.ai product routes (`/docs`, `/sheets`, `/design`,
 * `/slides`, `/make3d`, `/build`): a pill-tab row (or a section heading), then
 * a template shelf under the composer. Titles are content, not chrome, and stay
 * English exactly like kimi.ai. Thumbs are generated from Brand Book tokens —
 * no kimi CDN hotlinks.
 */
import type { ShellView } from '../lib/shellView';

export type ShowcaseCard = {
  id: string;
  title: string;
  accent: string;
  accent2: string;
  /** Masonry lanes only: taller thumb (kimi waterfall mixes 0.75 and 1 ratios). */
  tall?: boolean;
  /** Tab ids this card belongs to; empty/missing = every tab. */
  tabs?: readonly string[];
};

export type ShowcaseTab = { id: string; label: string };

export type ProductShowcaseData = {
  /** Section label when the shelf has no pill tabs. */
  heading?: string;
  tabs?: readonly ShowcaseTab[];
  /** Trailing control ("Shuffle") on heading rows. */
  action?: 'shuffle';
  cards: readonly ShowcaseCard[];
  /** Waterfall (variable height, no titles) — kimi `/make3d` and `/build`. */
  masonry?: boolean;
};

const BLUE = 'var(--kimi-brand-blue)';
const NAVY = 'var(--kimi-brand-navy)';
const SOFT = 'var(--kimi-brand-blue-soft)';
const BRIGHT = 'var(--kimi-brand-blue-bright)';
const OBSIDIAN = 'var(--kimi-obsidian)';
const AMBER = 'var(--kimi-amber)';

const DOCS: ProductShowcaseData = {
  heading: 'Featured document examples',
  cards: [
    { id: 'docs-tesla', title: 'Tesla tear sheet', accent: NAVY, accent2: BLUE },
    { id: 'docs-dress', title: 'Summer Dress Design', accent: SOFT, accent2: BLUE },
    { id: 'docs-hedge', title: 'Portfolio Hedging Toolkit', accent: BLUE, accent2: OBSIDIAN },
  ],
};

const SHEETS: ProductShowcaseData = {
  heading: 'Featured spreadsheet examples',
  action: 'shuffle',
  cards: [
    { id: 'sheets-biblio', title: 'Bibliometric Knowledge Graph', accent: BLUE, accent2: NAVY },
    { id: 'sheets-hermes', title: 'Hermès 20-Year Panorama', accent: AMBER, accent2: NAVY },
    { id: 'sheets-health', title: 'Personal Health Dashboard', accent: BRIGHT, accent2: BLUE },
  ],
};

const DESIGN: ProductShowcaseData = {
  heading: 'Featured design examples',
  action: 'shuffle',
  cards: [
    { id: 'design-brand', title: 'Brand Identity Kit', accent: BLUE, accent2: OBSIDIAN },
    { id: 'design-editorial', title: 'Editorial Landing Page', accent: SOFT, accent2: NAVY },
    { id: 'design-app', title: 'Mobile App Concept', accent: BRIGHT, accent2: BLUE },
  ],
};

const SLIDES_TABS: readonly ShowcaseTab[] = [
  { id: 'all', label: 'All Templates' },
  { id: 'custom', label: 'Custom' },
  { id: 'work', label: 'Work' },
  { id: 'finance', label: 'Finance' },
  { id: 'promotion', label: 'Promotion' },
  { id: 'academic', label: 'Academic' },
  { id: 'consulting', label: 'Consulting' },
];

const SLIDES: ProductShowcaseData = {
  tabs: SLIDES_TABS,
  cards: [
    {
      id: 'slides-course',
      title: 'Blue Line Courseware',
      accent: BLUE,
      accent2: NAVY,
      tabs: ['custom', 'academic'],
    },
    {
      id: 'slides-charity',
      title: 'Aqua Charity Report',
      accent: SOFT,
      accent2: BRIGHT,
      tabs: ['work', 'consulting'],
    },
    {
      id: 'slides-apricot',
      title: 'Apricot White Brief',
      accent: AMBER,
      accent2: SOFT,
      tabs: ['work', 'promotion'],
    },
    {
      id: 'slides-pitch',
      title: 'Series A Pitch Deck',
      accent: NAVY,
      accent2: BLUE,
      tabs: ['finance', 'consulting'],
    },
    {
      id: 'slides-review',
      title: 'Quarterly Business Review',
      accent: BLUE,
      accent2: BRIGHT,
      tabs: ['finance', 'work'],
    },
    {
      id: 'slides-lecture',
      title: 'Lecture Deck',
      accent: OBSIDIAN,
      accent2: BLUE,
      tabs: ['academic'],
    },
  ],
};

const MAKE3D_TABS: readonly ShowcaseTab[] = [
  { id: 'featured', label: 'Featured Templates' },
  { id: 'industrial', label: 'Industrial Design & Art' },
  { id: 'everyday', label: 'Everyday Finds' },
  { id: 'architecture', label: 'Architectural Design' },
  { id: 'science', label: 'Science & Technology' },
  { id: 'games', label: 'Games' },
  { id: 'other', label: 'Other' },
];

const MAKE3D: ProductShowcaseData = {
  tabs: MAKE3D_TABS,
  masonry: true,
  cards: [
    {
      id: '3d-cathedral',
      title: 'Cologne Cathedral',
      accent: NAVY,
      accent2: OBSIDIAN,
      tall: true,
      tabs: ['architecture'],
    },
    { id: '3d-lamp', title: 'Desk Lamp Study', accent: SOFT, accent2: BLUE, tabs: ['industrial'] },
    { id: '3d-vase', title: 'Ceramic Vase', accent: BLUE, accent2: SOFT, tabs: ['industrial'] },
    {
      id: '3d-orbit',
      title: 'Orbital Station',
      accent: OBSIDIAN,
      accent2: BLUE,
      tall: true,
      tabs: ['science'],
    },
    { id: '3d-figurine', title: 'Resin Figurine', accent: AMBER, accent2: NAVY, tabs: ['games'] },
    { id: '3d-pavilion', title: 'Concrete Pavilion', accent: BRIGHT, accent2: NAVY, tall: true },
    { id: '3d-mug', title: 'Everyday Mug', accent: SOFT, accent2: NAVY, tabs: ['everyday'] },
    {
      id: '3d-arcade',
      title: 'Arcade Cabinet',
      accent: BLUE,
      accent2: OBSIDIAN,
      tall: true,
      tabs: ['games'],
    },
    { id: '3d-drone', title: 'Survey Drone', accent: NAVY, accent2: BRIGHT, tabs: ['science'] },
    { id: '3d-keycap', title: 'Keycap Set', accent: OBSIDIAN, accent2: SOFT, tabs: ['industrial'] },
    { id: '3d-table', title: 'Side Table', accent: SOFT, accent2: AMBER, tabs: ['everyday'] },
    {
      id: '3d-terrain',
      title: 'Terrain Model',
      accent: BRIGHT,
      accent2: OBSIDIAN,
      tall: true,
      tabs: ['science'],
    },
  ],
};

const BUILD_TABS: readonly ShowcaseTab[] = [
  { id: 'all', label: 'All Templates' },
  { id: 'games', label: 'Games' },
  { id: '3d', label: '3D' },
  { id: 'tools', label: 'Personal Tools' },
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'marketing', label: 'Marketing' },
  { id: 'education', label: 'Education' },
  { id: 'saas', label: 'Saas' },
  { id: 'creatives', label: 'Creatives' },
  { id: 'report', label: 'InteractiveReport' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'content', label: 'Content' },
];

const BUILD: ProductShowcaseData = {
  tabs: BUILD_TABS,
  masonry: true,
  cards: [
    {
      id: 'build-portfolio',
      title: 'Studio Portfolio',
      accent: BLUE,
      accent2: OBSIDIAN,
      tall: true,
      tabs: ['portfolio', 'creatives'],
    },
    {
      id: 'build-dashboard',
      title: 'Analytics Dashboard',
      accent: NAVY,
      accent2: BLUE,
      tabs: ['dashboard', 'saas'],
    },
    { id: 'build-quiz', title: 'Quiz App', accent: SOFT, accent2: BLUE, tabs: ['education'] },
    {
      id: 'build-game',
      title: 'Brick Breaker',
      accent: BRIGHT,
      accent2: NAVY,
      tall: true,
      tabs: ['games'],
    },
    { id: 'build-3d', title: '3D Product Viewer', accent: OBSIDIAN, accent2: BRIGHT, tabs: ['3d'] },
    {
      id: 'build-landing',
      title: 'SaaS Landing',
      accent: BLUE,
      accent2: SOFT,
      tall: true,
      tabs: ['marketing', 'saas'],
    },
    { id: 'build-tool', title: 'Unit Converter', accent: SOFT, accent2: OBSIDIAN, tabs: ['tools'] },
    {
      id: 'build-report',
      title: 'Interactive Report',
      accent: NAVY,
      accent2: SOFT,
      tabs: ['report'],
    },
    { id: 'build-blog', title: 'Content Hub', accent: AMBER, accent2: NAVY, tabs: ['content'] },
  ],
};

/**
 * Kimi serves `/work`, `/code`, `/claw` and the platform portal on separate
 * marketing hosts, so those shelves carry our own template set instead of a
 * verified kimi.ai copy — they keep the landing surface from being blank.
 */
const WORK: ProductShowcaseData = {
  heading: 'Featured work templates',
  action: 'shuffle',
  cards: [
    { id: 'work-okr', title: 'Quarterly OKR Review', accent: NAVY, accent2: BLUE },
    { id: 'work-spec', title: 'Product Spec Draft', accent: BLUE, accent2: SOFT },
    { id: 'work-onboarding', title: 'Onboarding Checklist', accent: BRIGHT, accent2: NAVY },
  ],
};

const CODE: ProductShowcaseData = {
  heading: 'Featured code projects',
  action: 'shuffle',
  cards: [
    { id: 'code-api', title: 'REST API Scaffold', accent: OBSIDIAN, accent2: BLUE },
    { id: 'code-tests', title: 'Test Suite Generator', accent: BLUE, accent2: NAVY },
    { id: 'code-migrate', title: 'Schema Migration', accent: SOFT, accent2: NAVY },
  ],
};

const CLAW: ProductShowcaseData = {
  heading: 'Featured automations',
  action: 'shuffle',
  cards: [
    { id: 'claw-inbox', title: 'Inbox Triage', accent: BLUE, accent2: OBSIDIAN },
    { id: 'claw-report', title: 'Weekly Report Bot', accent: SOFT, accent2: BLUE },
    { id: 'claw-monitor', title: 'Doc Monitor', accent: AMBER, accent2: NAVY },
  ],
};

const PLATFORM: ProductShowcaseData = {
  heading: 'Featured integrations',
  cards: [
    { id: 'platform-edms', title: 'EDMS Connector', accent: NAVY, accent2: BRIGHT },
    { id: 'platform-graph', title: 'Knowledge Graph API', accent: BLUE, accent2: OBSIDIAN },
    { id: 'platform-stream', title: 'Streaming Gateway', accent: SOFT, accent2: NAVY },
  ],
};

/** Shelves rendered under the composer for kimi product routes. */
export const PRODUCT_SHOWCASES: Partial<Record<ShellView, ProductShowcaseData>> = {
  docs: DOCS,
  sheets: SHEETS,
  design: DESIGN,
  slides: SLIDES,
  make3d: MAKE3D,
  build: BUILD,
  work: WORK,
  code: CODE,
  claw: CLAW,
  platform: PLATFORM,
};
