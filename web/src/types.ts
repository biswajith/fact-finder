// Shapes of the JSON the backend returns (WEB_UI_SPEC.md sections 4 to 6).

export type CategoryCode = 'B' | 'C' | 'G' | 'X' | 'D' | 'S' | 'E' | 'R' | 'Q';
export type Flag = 'mandatory' | 'desirable' | 'risk' | 'unclear' | 'replaced' | 'post-award';
export type FactStatus = 'valid' | 'needs_review' | 'conflict';

export const CATEGORY_CODES: CategoryCode[] = ['B', 'C', 'G', 'X', 'D', 'S', 'E', 'R', 'Q'];
export const CATEGORY_NAMES: Record<CategoryCode, string> = {
  B: 'Buyer information',
  C: 'Contract details',
  G: 'Go/no-go gate',
  X: 'Disqualification criterion',
  D: 'Date',
  S: 'Submission delivery',
  E: 'Evaluation criterion',
  R: 'Requirement',
  Q: 'Contradiction',
};
export const FLAGS: Flag[] = ['mandatory', 'desirable', 'risk', 'unclear', 'replaced', 'post-award'];

export interface Status {
  model: string;
  has_key: boolean;
  runs_folder: string;
}

export interface RunInfo {
  run: string;
  doc_id: string;
  run_id: string;
  facts: number;
  modified: string | number;
  has_pdf: boolean;
  corrections: number;
  pdf_name?: string | null;
}

export interface Citation {
  id: string;
  page: number;
  page_label: string;
  section: string;
  text: string;
  bbox: [number, number, number, number] | null;
}

export interface Resolution {
  conflict_id?: string;
  option?: number | null;
  label: string;
  text: string;
  at: string;
}

export interface Fact {
  fact_id: string;
  deal_id?: string;
  doc_id?: string;
  run_id?: string;
  category: CategoryCode;
  text: string;
  citations: Citation[];
  unresolved_ids: string[];
  flags: Flag[];
  note: string;
  status: FactStatus;
  source_call?: string;
  problems: string[];
  conflicts: string[];
  origin: 'extracted' | 'user';
  edited: boolean;
  deleted: boolean;
  original: Partial<Pick<Fact, 'text' | 'category' | 'flags' | 'note'>> | null;
  resolution: Resolution | null;
  corrections: string[];
  // Added by GET /facts and /facts/list (spec 11.1).
  post_award?: boolean;
  affects_bid?: boolean;
  split?: boolean;
  // Present because the backend spreads the normalized record (runs.normalize); older runs have empty values.
  votes?: string[];
  agreement?: string;
  also?: string;
  group_id?: string;
  group_kind?: string;
  group_title?: string;
}

export interface FactsResponse {
  doc_id: string;
  run_id: string;
  pages: number;
  facts: Fact[];
}

export interface NewFact {
  category: CategoryCode;
  text: string;
  flags?: Flag[];
  note?: string;
  citation_ids?: string[];
}

export interface FactPatch {
  text?: string;
  category?: CategoryCode;
  flags?: Flag[];
  note?: string;
  reason?: string;
}

export interface ConflictChange {
  op: 'edit' | 'delete';
  fact_id: string;
  fields?: Record<string, unknown>;
}

export interface ConflictOption {
  label: string;
  text: string;
  citation?: { id: string; page: number; page_label: string; section: string } | null;
  changes: ConflictChange[];
}

export interface Conflict {
  id: string;
  kind: 'source' | 'raised';
  title: string;
  description: string;
  fact_ids: string[];
  options: ConflictOption[];
  status: 'open' | 'resolved';
  resolution: { option: number | null; label: string; text: string; at: string } | null;
}

export type ResolveBody = { option: number } | { text: string };

export interface CorrectionEntry {
  id: string;
  at: string;
  source: 'chat' | 'ui';
  op: 'edit' | 'delete' | 'add' | 'raise' | 'resolve' | 'undo';
  fact_id: string | null;
  fields: Record<string, unknown> | null;
  reason: string | null;
  conflict_id: string | null;
  target: string | null;
  undone: boolean;
  fact_text: string | null;
}

export interface SummaryRow {
  row: string;
  text: string;
  page: string;
  fact_ids: string[];
  checked: boolean;
}

export interface SummarySection {
  key: string;
  title: string;
  codes: string[];
  rows: SummaryRow[];
  source: 'extraction' | 'app' | null;
  generated_at: string | null;
  stale: boolean;
  updating: boolean;
  fact_count: number;
  uncovered: string[];
  error: string | null;
}

export interface SummariesResponse {
  sections: SummarySection[];
  updating: boolean;
}

export interface ToolStep {
  name: string;
  label: string;
  ok: boolean;
  /** Logged with stored chats only: the tool's arguments and a short result. */
  args?: Record<string, unknown>;
  summary?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  at: string;
  text: string;
  tools?: ToolStep[];
  conflict_ids?: string[];
}

export type ChangedWhat = 'facts' | 'conflicts' | 'summaries';

export type ChatEvent =
  | { type: 'text'; delta: string }
  | ({ type: 'tool' } & ToolStep)
  | { type: 'changed'; what: ChangedWhat[] }
  | { type: 'conflict'; conflict_id: string }
  | { type: 'error'; message: string }
  | { type: 'done'; message: ChatMessage };

// ---- Features carried over from the Streamlit app (spec 11) -------------------------------

export type ViewName = 'All' | 'Bid' | 'After award';

/** A line of a summary card; `children` is non-empty for a list (`runs._entries`). */
export interface OverviewEntry {
  text: string;
  page: string;
  children: { text: string; page: string }[];
}
export interface CalendarDate {
  date: string;
  label: string;
  time: string;
  text: string;
  page: string;
}
export interface Overview {
  buyer_facts: OverviewEntry[];
  gates: OverviewEntry[];
  disqualifiers: OverviewEntry[];
  submission: OverviewEntry[];
  contradictions: OverviewEntry[];
  unclear: OverviewEntry[];
  scoring: OverviewEntry[];
  calendar: { dated: CalendarDate[]; undated: { text: string; page: string }[] };
}
export interface OverviewCounts {
  needs_review: number;
  conflicts: number;
  risk: number;
  mandatory: number;
  unclear: number;
}
export interface OverviewResponse {
  overview: Overview;
  counts: OverviewCounts;
  by_category: Record<string, number>;
  has_post_award: boolean;
  views: ViewName[];
}

export interface FactsListFilters {
  q: string;
  categories: string[];
  statuses: FactStatus[];
  flags: Flag[];
  pageFrom: number | null;
  pageTo: number | null;
  view: ViewName;
  splitOnly: boolean;
  edited: boolean;
  includeDeleted: boolean;
}

export interface FactItem {
  kind: 'fact' | 'same' | 'list';
  fact_ids: string[];
}
export interface FactsListResponse {
  total: number;
  by_category: Record<string, number>;
  items: FactItem[];
  facts: Fact[];
}

export interface ReportCall {
  name?: string;
  kind?: string;
  status?: string;
  seconds?: number;
  lines?: number;
  retries?: number;
  usage?: { output_tokens?: number } | null;
  log?: unknown[];
  output?: string;
}
/** report.json as the run stored it; every field is optional (older runs lack some). */
export interface Report {
  seconds?: Record<string, number>;
  output_tokens?: number;
  cache_hit_calls_2_to_n?: number;
  calls?: ReportCall[];
  failed_calls?: unknown[];
  incomplete_calls?: unknown[];
  units_unanswered_votes?: number;
}

export interface RunsTableRow {
  run: string;
  document: string;
  facts: number;
  'total s': number | null;
  'extract s': number | null;
  'sweep and check s': number | null;
  'output tokens': number | null;
  finished: string;
}

export interface Agreement {
  facts: [number, number];
  cited_ids: [number, number];
  cited_both: number;
  id_agreement: number | null;
  same_codes: number;
  code_agreement: number | null;
  same_fact_id: number;
  fact_id_agreement: number | null;
  by_category: Record<string, { a: number; b: number; ids_both: number }>;
  /** [[codesOnlyInOne, codesOnlyInOther], count] (tuples serialize as arrays). */
  code_flips: [[string, string], number][];
}
export interface CodeDifference {
  id: string;
  codes_a: string;
  codes_b: string;
  facts_a: string;
  facts_b: string;
}
export interface CompareResponse {
  agreement: Agreement;
  code_differences: CodeDifference[];
}

export interface PdfChoice {
  path: string;
  name: string;
}
export interface PdfState {
  has_pdf: boolean;
  name?: string;
}
export interface UploadInfo {
  upload_id: string;
  name: string;
  pages: number;
}
export type PdfSource = { path: string } | { upload_id: string };
export interface PlanRow {
  call: string;
  times: number;
  units: number;
  pages: string;
}
export interface ExtractPlan {
  calls: PlanRow[];
  total_calls: number;
  units: number;
  stored: { run: string; facts: number; created: string } | null;
}
export interface ExtractRequest {
  deal_id: string;
  doc_id: string;
  model?: string;
  votes: number;
  confirm: true;
}
export interface ExtractJob {
  status: 'running' | 'done' | 'failed';
  seconds: number;
  result: string | null;
  run: string | null;
  error: string | null;
}
