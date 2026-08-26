export type IconToken =
  | "calendar"
  | "mail"
  | "search"
  | "document"
  | "warning"
  | "success"
  | "danger"
  | "info"
  | "user"
  | "users"
  | "clock"
  | "chart"
  | "shield"
  | "check"
  | "x"
  | "link"
  | "edit"
  | "settings";

export type CalloutTone = "info" | "success" | "warning" | "danger";
export type ListStyle = "ordered" | "unordered";
export type ChartKind = "bar" | "line" | "pie";
export type StepStatus = "pending" | "active" | "done" | "blocked";
export type ActionKind = "approve" | "reject" | "confirm" | "dismiss" | "custom";
export type ActionStyle = "primary" | "secondary" | "danger";
/** Opaque id resolved by UI registry — not a platform product enum. */
export type WidgetKind = string;

export type HeadingBlock = {
  type: "heading";
  level: 1 | 2 | 3;
  text: string;
  icon?: IconToken | null;
};

export type ParagraphBlock = {
  type: "paragraph";
  text: string;
};

export type ListItem = {
  text: string;
  icon?: IconToken | null;
  emphasis?: string | null;
};

export type ListBlock = {
  type: "list";
  style: ListStyle;
  items: ListItem[];
};

export type TableBlock = {
  type: "table";
  columns: string[];
  rows: string[][];
};

export type CalloutBlock = {
  type: "callout";
  tone: CalloutTone;
  title?: string | null;
  body: string;
  icon?: IconToken | null;
};

export type CodeBlock = {
  type: "code";
  language: string;
  content: string;
};

export type FormulaBlock = {
  type: "formula";
  latex: string;
};

export type KeyValueItem = {
  label: string;
  value: string;
  icon?: IconToken | null;
};

export type KeyValueBlock = {
  type: "kv";
  items: KeyValueItem[];
};

export type StepItem = {
  title: string;
  body: string;
  status: StepStatus;
  icon?: IconToken | null;
};

export type StepsBlock = {
  type: "steps";
  items: StepItem[];
};

export type ChartSeries = {
  name: string;
  values: number[];
};

export type ChartBlock = {
  type: "chart";
  kind: ChartKind;
  labels: string[];
  series: ChartSeries[];
  title?: string | null;
};

export type DividerBlock = {
  type: "divider";
};

export type WidgetBlock = {
  type: "widget";
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

export type DocumentMeta = {
  confidence: number;
  requires_review: boolean;
  source_refs: string[];
  interaction?: "none" | "choice" | "confirm";
};

export type ContentDocument = {
  schema_version: 1;
  locale: string;
  title?: string | null;
  blocks: ContentBlock[];
  actions: ActionSpec[];
  meta: DocumentMeta;
};

export type FormatterTaskResult = {
  task_id: string;
  agent_role: string;
  status: "success" | "failure" | "partial";
  confidence: number;
  requires_review: boolean;
  error: string | null;
  output: ContentDocument | null;
  hitl_cards: HITLCardView[];
};

export type HITLCardStatus =
  | "pending"
  | "resolved"
  | "expired"
  | "escalated"
  | "auto_rejected"
  | "dead_letter";

export type HITLOption = {
  action_id: string;
  label: string;
  kind: ActionKind;
  style: ActionStyle;
  icon?: IconToken | null;
  action_token: string;
};

export type HITLCardPurpose = "quality_review" | "mcp_tool_approval" | "user_choice";

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
};

export type HITLResolveResult = {
  card: HITLCardView;
  replayed: boolean;
  message: string;
};

export type HitlRespondResponse = {
  resolve: HITLResolveResult;
  resumed?: FormatterTaskResult | null;
};
