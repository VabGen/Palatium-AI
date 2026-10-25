export type IconToken =
  | 'calendar'
  | 'mail'
  | 'search'
  | 'document'
  | 'warning'
  | 'success'
  | 'danger'
  | 'info'
  | 'user'
  | 'users'
  | 'clock'
  | 'chart'
  | 'shield'
  | 'check'
  | 'x'
  | 'link'
  | 'edit'
  | 'settings';

export type CalloutTone = 'info' | 'success' | 'warning' | 'danger';
export type ListStyle = 'ordered' | 'unordered';
export type ChartKind = 'bar' | 'line' | 'pie';
export type StepStatus = 'pending' | 'active' | 'done' | 'blocked';
export type ActionKind = 'approve' | 'reject' | 'confirm' | 'dismiss' | 'custom' | 'format';
export type ActionStyle = 'primary' | 'secondary' | 'danger';
/** Opaque id resolved by UI registry — not a platform product enum. */
export type WidgetKind = string;

export type HeadingBlock = {
  type: 'heading';
  level: 1 | 2 | 3;
  text: string;
  icon?: IconToken | null;
};

export type ParagraphBlock = {
  type: 'paragraph';
  text: string;
  icon?: IconToken | null;
};

export type ListItem = {
  text: string;
  icon?: IconToken | null;
  emphasis?: string | null;
};

export type ListBlock = {
  type: 'list';
  style: ListStyle;
  items: ListItem[];
};

export type TableBlock = {
  type: 'table';
  columns: string[];
  rows: string[][];
};

export type CalloutBlock = {
  type: 'callout';
  tone: CalloutTone;
  title?: string | null;
  body: string;
  icon?: IconToken | null;
};

export type CodeBlock = {
  type: 'code';
  language: string;
  content: string;
};

export type FormulaBlock = {
  type: 'formula';
  latex: string;
};

export type KeyValueItem = {
  label: string;
  value: string;
  icon?: IconToken | null;
};

export type KeyValueBlock = {
  type: 'kv';
  items: KeyValueItem[];
};

export type StepItem = {
  title: string;
  body: string;
  status: StepStatus;
  icon?: IconToken | null;
};

export type StepsBlock = {
  type: 'steps';
  items: StepItem[];
};

export type ChartSeries = {
  name: string;
  values: number[];
};

export type ChartBlock = {
  type: 'chart';
  kind: ChartKind;
  labels: string[];
  series: ChartSeries[];
  title?: string | null;
};

export type DividerBlock = {
  type: 'divider';
};

export type WidgetBlock = {
  type: 'widget';
  kind: WidgetKind;
  ref_id: string;
  title?: string | null;
  href?: string | null;
};

export type ContentBlock =
  | HeadingBlock
  | ParagraphBlock
  | ListBlock
  | TableBlock
  | CalloutBlock
  | CodeBlock
  | FormulaBlock
  | KeyValueBlock
  | StepsBlock
  | ChartBlock
  | DividerBlock
  | WidgetBlock;

export type ActionSpec = {
  action_id: string;
  label: string;
  kind: ActionKind;
  style: ActionStyle;
  icon?: IconToken | null;
  requires_confirmation: boolean;
  risk_score: number;
};

export type CitationAnchor =
  'char_location' | 'page_location' | 'content_block_location' | 'url_only';

/**
 * Provider citation anchor (mirror of `domain/content/citations/models.py`, W3b).
 *
 * Two coordinate spaces, never one: `answer_range` is an offset inside the text the
 * provider annotated (the raw answer), `source_range`/`page` point into the source.
 * `missing` (undefined) means "the provider did not say" — not zero.
 */
export type CitationRef = {
  source_ref: string;
  /**
   * Attachment id bound by the server when the label names exactly one upload.
   * Absent when the label is ambiguous or the source is an external URL — the UI then
   * offers no "show in source" action instead of opening a same-named file.
   */
  source_id?: string | null;
  quote?: string | null;
  page?: number | null;
  source_range?: [number, number] | null;
  answer_range?: [number, number] | null;
  anchor: CitationAnchor;
};

export type DocumentMeta = {
  confidence: number;
  requires_review: boolean;
  source_refs: string[];
  interaction?: 'none' | 'choice' | 'confirm';
  /** Length axis stamped by the server (W7); absent on legacy/persisted payloads. */
  verbosity_budget?: 'minimal' | 'standard' | 'detailed';
  /** Resolved provider anchors; absent on legacy/persisted payloads (W3b). */
  citations?: CitationRef[];
};

export type ContentDocument = {
  schema_version: 1;
  locale: string;
  title?: string | null;
  blocks: ContentBlock[];
  actions: ActionSpec[];
  meta: DocumentMeta;
};

/**
 * Block-level delta against the previous answer (W7b, mirror of
 * `domain/content/revision.py`).
 *
 * `changed_block_indices` are positions inside **this** document, in the same order as
 * `changed_blocks`. The server sends them precisely so the client never re-implements
 * the Python content hash: a re-derived hash that drifts (number formatting, a new field)
 * would fail silently by simply not highlighting anything.
 *
 * `changed_block_indices` is absent on turns persisted before the UI wave; the note then
 * states the counts without marking blocks, instead of guessing positions.
 */
export type DocumentRevision = {
  revision_of: string;
  changed_blocks: string[];
  changed_block_indices?: number[];
  removed_blocks: string[];
  unchanged_blocks: number;
};

export type FormatterTaskResult = {
  task_id: string;
  agent_role: string;
  status: 'success' | 'failure' | 'partial';
  confidence: number;
  requires_review: boolean;
  error: string | null;
  output: ContentDocument | null;
  hitl_cards: HITLCardView[];
};

export type HITLCardStatus =
  'pending' | 'resolved' | 'expired' | 'escalated' | 'auto_rejected' | 'dead_letter';

export type HITLOption = {
  action_id: string;
  label: string;
  kind: ActionKind;
  style: ActionStyle;
  icon?: IconToken | null;
  action_token: string;
};

export type HITLCardPurpose = 'quality_review' | 'mcp_tool_approval' | 'user_choice';

export type HITLCardView = {
  card_id: string;
  thread_id: string;
  task_id: string;
  purpose?: HITLCardPurpose;
  title: string;
  body?: string | null;
  options: HITLOption[];
  risk_score: number;
  status: HITLCardStatus;
  created_at: string;
  expires_at: string;
  resolved_action_id?: string | null;
  resolved_at?: string | null;
  owner_user_id?: string | null;
  org_id?: string | null;
  content_sha256?: string | null;
  token_nonce?: string | null;
  escalate_to_roles?: string[] | null;
};

export type HitlStepUpChallenge = {
  required: boolean;
  method: string;
  required_acr?: string | null;
  card_claim?: string | null;
  challenge?: string | null;
  authorize_url?: string | null;
  assertion?: string | null;
};

export type DialogTurnResponse = {
  id?: string | null;
  thread_id: string;
  role: string;
  content: string;
  payload?: Record<string, unknown> | null;
  task_id?: string | null;
  seq: number;
  created_at?: string | null;
};

export type HITLResolveResult = {
  card: HITLCardView;
  replayed: boolean;
  message: string;
};

export type HitlRespondResponse = {
  resolve: HITLResolveResult;
  resumed?: FormatterTaskResult | null;
  revision?: DocumentRevision | null;
};
