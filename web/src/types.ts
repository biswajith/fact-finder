// Shapes of the JSON the backend returns (WEB_UI_SPEC.md sections 4 to 6).

export type CategoryCode = 'B' | 'C' | 'G' | 'X' | 'D' | 'S' | 'E' | 'R' | 'Q'
  | 'PRIORITY' | 'DECIDER' | 'BUDGET' | 'QUESTION' | 'COMPETITOR' | 'ACTION';
export type Flag = 'mandatory' | 'desirable' | 'risk' | 'unclear' | 'replaced' | 'post-award'
  | 'tentative' | 'precedence' | 'both-sides';
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
  PRIORITY: 'Buyer priority',
  DECIDER: 'Decision maker',
  BUDGET: 'Budget',
  QUESTION: 'Open question',
  COMPETITOR: 'Competitor',
  ACTION: 'Action for our team',
};
/** Codes only the call-transcript and deal-notes playbooks give; they appear in a bid only. */
export const BID_CATEGORY_CODES: CategoryCode[] = ['PRIORITY', 'DECIDER', 'BUDGET', 'QUESTION', 'COMPETITOR', 'ACTION'];
export const FLAGS: Flag[] = ['mandatory', 'desirable', 'risk', 'unclear', 'replaced', 'post-award'];
/** Flags that only a bid's facts carry. */
export const BID_FLAGS: Flag[] = ['tentative', 'precedence', 'both-sides'];

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
  /** Set on the rows of a bid (run `_bids/<bid_id>`). */
  kind?: 'bid';
  name?: string;
  documents?: number;
}

export interface Citation {
  id: string;
  page: number;
  page_label: string;
  section: string;
  text: string;
  bbox: [number, number, number, number] | null;
  // Added for a bid (runs.normalize gives every citation these; outside a bid they are empty).
  doc_id?: string;
  doc_no?: number;
  /** Transcripts: who said it (the page label is then the time). */
  speaker?: string;
  side?: string;
  level?: number;
  visibility?: 'external' | 'internal';
}

/** One end of a relation between two documents. `fact_id` is "" when no fact stands on that unit. */
export interface RelationEnd {
  doc_id: string;
  unit: string;
  fact_id: string;
}
export type RelationKind = 'REPLACES' | 'REMOVES' | 'ADDS' | 'CLARIFIES' | 'CONFIRMS' | 'DISAGREES';
export interface Relation {
  id: string;
  kind: RelationKind;
  from: RelationEnd;
  to: RelationEnd;
  rejected: boolean;
}

/** A document of a bid as GET /facts lists it (issue order). */
export interface FactsDocument {
  no: number;
  doc_id: string;
  file_name: string;
  playbook: string;
  level: string;
  visibility: 'external' | 'internal';
  issue_date: string | null;
  issue_number: number | null;
  has_pdf: boolean;
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
  // Added in a bid's facts.json.
  doc_no?: number;
  /** 1 buyer document, 2 buyer on a call, 3 our side on a call, 4 deal notes; absent outside a bid. */
  level?: number;
  playbook?: string;
  relations?: Relation[];
  /** The fact that governs this one now, when it is replaced; "" when none (or a later document removed it). */
  replaced_by?: string;
  /** "" or a warning, as the server words it ("section partly replaced", "may conflict with <fact id>"). */
  stale?: string;
}

export interface FactsResponse {
  doc_id: string;
  run_id: string;
  pages: number;
  facts: Fact[];
  /** Only for a bid, in issue order. */
  documents?: FactsDocument[];
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
  /** A flag the workspace adds to the flags the fact has when the choice is made. */
  add_flag?: string;
}

export interface ConflictOption {
  label: string;
  text: string;
  citation?: { id: string; page: number; page_label: string; section: string } | null;
  changes: ConflictChange[];
  /** "Ask the buyer": nothing is applied. */
  question?: boolean;
}

export type DocumentConflictReason =
  | 'user-edited fact replaced' | 'old value elsewhere' | 'depends on changed value' | 'levels disagree'
  | 'unfound target' | 'issued together';

export interface Conflict {
  id: string;
  kind: 'source' | 'raised' | 'document';
  /** Document conflicts only. */
  reason?: DocumentConflictReason | string;
  /** Document conflicts only: the doc_id of the later document that settled it, or "". */
  closed_by?: string;
  doc_id?: string;
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
  op: 'edit' | 'delete' | 'add' | 'raise' | 'resolve' | 'undo' | 'reject_relation' | 'ungroup';
  fact_id: string | null;
  fields: Record<string, unknown> | null;
  reason: string | null;
  conflict_id: string | null;
  target: string | null;
  undone: boolean;
  fact_text: string | null;
  /** Edits: the changed fields' values just before this edit. */
  before?: Record<string, unknown>;
  /** Entries about a conflict: its title, when it is still listed. */
  conflict_title?: string | null;
  /** Choices: the chosen option's label, or "Your own answer: ...". */
  choice?: string | null;
  /** `reject_relation` and `ungroup` entries: a line in words from the server. */
  description?: string;
}

export interface SummaryRow {
  row: string;
  text: string;
  page: string;
  fact_ids: string[];
  checked: boolean;
  /** Set when the summary's wording failed the figure check and is not shown: the figures that were not in
   *  the facts it cites, or "it cites no facts". `text` is then the cited facts themselves (or empty). */
  unverified?: string[];
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

// ---- Overview, filtered facts, report, compare, PDFs, new run (spec 11) --------------------

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
  /** Bid only: document numbers (sent as `docs`) and levels (sent as `levels`). */
  docs: number[];
  levels: number[];
  /** Bid only, applied on the client to the list the server returns; never sent. */
  hideReplaced: boolean;
}

export interface FactItem {
  kind: 'fact' | 'same' | 'list';
  fact_ids: string[];
}
export interface FactsListResponse {
  total: number;
  by_category: Record<string, number>;
  items: FactItem[]; // fact IDs only: the facts themselves come from GET /facts
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

export interface ExtractJob {
  status: 'running' | 'done' | 'failed';
  seconds: number;
  result: string | null;
  run: string | null;
  error: string | null;
  /** Only jobs of a bid report steps. */
  steps?: JobStep[];
}

// ---- Bids: many documents, one fact list (docs/multi-document-build-plan.md, "Web API as built") ----

export type BidRole = 'base' | 'change' | 'context';
export type SpeakerSide = 'buyer' | 'ours' | 'unknown' | '';

export interface BidPlaybook {
  name: string;
  description: string;
  role: BidRole;
  form: string;
  /** "1", "by speaker" or "4". */
  level: string;
  visibility: 'external' | 'internal';
  calls: string[];
  votes: number;
}
export interface BidProposal {
  playbook: string;
  issue_number: number | null;
  issue_date: string | null;
  by: string;
  checked: boolean;
}
export interface BidSpeaker {
  id: string;
  name: string;
  side: SpeakerSide;
  proposed: SpeakerSide;
  why: string;
}
export type BidDocStatus = 'uploaded' | 'confirmed' | 'extracting' | 'extracted' | 'failed';
export interface BidDocument {
  no: number;
  doc_id: string;
  file: string;
  file_name: string;
  sha256: string;
  pages: number;
  proposed: BidProposal;
  playbook: string;
  issue_number: number | null;
  issue_date: string | null;
  confirmed: boolean;
  previous: string | null;
  speakers: BidSpeaker[];
  speakers_confirmed: boolean;
  run: string;
  status: BidDocStatus;
  error: string;
  /** What is still needed before the document can be read, as the server words it. */
  missing: string[];
}
export interface Bid {
  bid_id: string;
  name: string;
  deal_id: string;
  created: string;
  team: { name: string }[];
  precedence: string[] | null;
  documents: BidDocument[];
  /** doc_ids in issue order. */
  order: string[];
  /** `_bids/<bid_id>` once the bid has facts, else "". */
  run: string;
  playbooks: BidPlaybook[];
}
export interface BidSummary {
  bid_id: string;
  name: string;
  run: string;
  documents: number;
  facts: number;
  modified: string | number;
}
export interface BidDocumentPatch {
  doc_id?: string;
  playbook?: string;
  issue_number?: number | null;
  issue_date?: string | null;
  previous?: string | null;
  confirmed?: boolean;
  speakers?: { id: string; name: string; side: SpeakerSide }[];
  speakers_confirmed?: boolean;
}
export interface BidPatch {
  name?: string;
  team?: { name: string }[];
  precedence?: string[] | null;
}
export interface PlanRow {
  call: string;
  times: number;
  units: number;
  pages: string;
}
export interface BidPlanDocument {
  no: number;
  doc_id: string;
  file_name: string;
  playbook: string;
  missing: string[];
  units: number;
  calls: PlanRow[];
  total_calls: number;
  stored: { run: string; facts: number; created: string } | null;
  error: string;
}
export interface BidPlan {
  documents: BidPlanDocument[];
  skipped: { no: number; doc_id: string; why: string }[];
  relate_again: number[];
  total_calls: number;
}
export type StepStatus = 'running' | 'done' | 'reused' | 'failed';
export interface JobStep {
  /** 0 for the steps of the whole bid. */
  doc_no: number;
  step: string;
  status: StepStatus;
  detail: string;
}

// ---- Chat sessions and their event log (WEB_UI_SPEC.md 7.2) --------------------------------

export interface ChatTotals {
  llm_calls?: number;
  tool_calls?: number;
  decisions_calls?: number;
  input_tokens?: number;
  cached_tokens?: number;
  output_tokens?: number;
  decisions_input_tokens?: number;
  llm_seconds?: number;
  decisions_seconds?: number;
  seconds?: number;
  /** Estimated dollars (pricing.py at the time of logging); absent for older logs or unknown models. */
  cost_usd?: number;
  llm_cost_usd?: number;
  decisions_cost_usd?: number;
}

export interface ChatSession {
  session_id: string;
  started?: string;
  run?: string;
  turns: number;
  last?: string;
  current: boolean;
  totals: ChatTotals;
}

export interface DecisionsCall {
  model?: string;
  seconds?: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number;
  error?: string;
}

export interface PlanStep { step: string; done: boolean }

/** One line of events.jsonl. Fields beyond the common ones depend on `event`. */
export interface ChatLogEvent {
  at: string;
  session_id: string;
  turn_id: string;
  seq: number;
  event: 'user_message' | 'route' | 'feedback' | 'plan' | 'llm_call' | 'tool' | 'assistant_message' | 'turn_end' | string;
  text?: string;
  // route, feedback, plan
  mode?: string;
  source?: string;
  confidence?: number;
  probabilities?: Record<string, number>;
  note?: string;
  call?: DecisionsCall | null;
  verdict?: string;
  plan?: string;
  steps?: PlanStep[];
  plan_text?: string;
  status?: string;
  // llm_call
  purpose?: string;
  round?: number | null;
  messages?: number;
  tools_offered?: number;
  tools_allowed?: boolean;
  tool_calls?: { name: string; args: unknown }[];
  text_chars?: number;
  input_tokens?: number | null;
  cached_tokens?: number | null;
  output_tokens?: number | null;
  seconds?: number;
  model?: string;
  cost_usd?: number;
  error?: string;
  // tool
  name?: string;
  args?: unknown;
  ok?: boolean;
  summary?: string;
  // assistant_message, turn_end
  tools?: number;
  conflict_ids?: string[];
  totals?: ChatTotals;
}

export interface ChatSessionDetail {
  session: ChatSession | null;
  events: ChatLogEvent[];
}
