// Pure helpers for the bid intake: the bids list, the status of each document, the steps of the wizard, the progress of a run.
import type { Bid, BidDocument, BidPlaybook, BidSpeaker, BidSummary, ExtractJob, JobStep, SpeakerSide } from './types';

// ---- files ----

/** The file types the server takes (UPLOAD_TYPES). */
export const ACCEPTED = ['.pdf', '.docx', '.json', '.txt', '.md', '.csv', '.xlsx'];
export const isAccepted = (name: string): boolean => ACCEPTED.some((ext) => name.toLowerCase().endsWith(ext));

export type Format = 'pdf' | 'word' | 'sheet' | 'json' | 'text';
export const FORMAT_LABEL: Record<Format, string> = { pdf: 'PDF', word: 'Word', sheet: 'Spreadsheet', json: 'JSON', text: 'Text' };

/** What kind of file a name says it is, for its icon and its label. */
export function formatOf(name: string): Format {
  const n = name.toLowerCase();
  if (n.endsWith('.pdf')) return 'pdf';
  if (n.endsWith('.docx')) return 'word';
  if (n.endsWith('.xlsx') || n.endsWith('.csv')) return 'sheet';
  if (n.endsWith('.json')) return 'json';
  return 'text';
}

// ---- the bids list ----

export type Stage = 'Intake' | 'Reading' | 'Ready';

/** `Ready` once the bid has a fact list, `Reading` while its extraction runs, else `Intake`. */
export function stageOf(bid: Pick<BidSummary, 'bid_id' | 'run'>, readingBidId: string | null): Stage {
  if (readingBidId === bid.bid_id) return 'Reading';
  return bid.run ? 'Ready' : 'Intake';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** A date written YYYY-MM-DD as a reader says it ("2 Sep 2026"); empty for none; a value that is not a date is shown as it is. */
export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${Number(m[3])} ${month} ${m[1]}` : iso;
}

/** How long ago, as "just now", "5 minutes ago", "3 hours ago", "2 days ago"; older than a month, the date. `at` is an ISO time or epoch seconds. */
export function agoLabel(at: string | number | null | undefined, now: number = Date.now()): string {
  if (at === null || at === undefined || at === '') return '';
  const t = typeof at === 'number' ? at * 1000 : Date.parse(at);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'} ago`;
  if (s < 60) return 'just now';
  if (s < 3600) return plural(Math.floor(s / 60), 'minute');
  if (s < 86400) return plural(Math.floor(s / 3600), 'hour');
  if (s < 86400 * 31) return plural(Math.floor(s / 86400), 'day');
  return dateLabel(new Date(t).toISOString().slice(0, 10));
}

/** The customers named on the bids, each once, in the order of the list. */
export function customersOf(bids: Pick<BidSummary, 'customer'>[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const b of bids ?? []) {
    const c = (b.customer ?? '').trim();
    if (c && !seen.has(c.toLowerCase())) {
      seen.add(c.toLowerCase());
      out.push(c);
    }
  }
  return out;
}

/** People from the teams of several bids, each name once (the first role given wins), skipping those in `exclude`. */
export function peopleOf(teams: { name: string; role?: string }[][], exclude: string[] = []): { name: string; role: string }[] {
  const seen = new Set(exclude.map((n) => n.trim().toLowerCase()));
  const out: { name: string; role: string }[] = [];
  for (const team of teams) {
    for (const t of team) {
      const name = (t.name ?? '').trim();
      if (name && !seen.has(name.toLowerCase())) {
        seen.add(name.toLowerCase());
        out.push({ name, role: (t.role ?? '').trim() });
      }
    }
  }
  return out;
}

// ---- one document ----

/** The server's reasons about the speakers of a call; the Documents step does not wait for them. */
const SPEAKER_WORDS = ['speakers not read yet', 'speakers not confirmed', 'a speaker has no side'];

export const playbookOf = (bid: Pick<Bid, 'playbooks'>, doc: Pick<BidDocument, 'playbook'>): BidPlaybook | undefined =>
  bid.playbooks.find((p) => p.name === doc.playbook);

/** What the document still needs from the reader before it can be confirmed (or, once confirmed, read): "issue date", "issue number", "earlier issue". */
export function gapsOf(
  doc: Pick<BidDocument, 'issue_number' | 'issue_date' | 'previous'>,
  playbook: Pick<BidPlaybook, 'name' | 'role'> | null | undefined,
): string[] {
  if (!playbook) return [];
  const out: string[] = [];
  if ((playbook.role === 'change' || playbook.role === 'context') && !doc.issue_date) out.push('issue date');
  if (playbook.role === 'change' && !doc.issue_number) out.push('issue number');
  if (playbook.name === 'reissued-rfp' && !doc.previous) out.push('earlier issue');
  return out;
}

/** Whether the server still waits for something about the speakers of this document. */
export const waitsForSpeakers = (doc: Pick<BidDocument, 'missing'>): boolean => doc.missing.some((m) => SPEAKER_WORDS.includes(m));

/** The call has not had its speakers read (no key at upload, or the model did not answer). */
export const speakersUnread = (doc: Pick<BidDocument, 'missing'>): boolean => doc.missing.includes('speakers not read yet');

export const isExtracted = (doc: Pick<BidDocument, 'run' | 'status'>): boolean => !!doc.run || doc.status === 'extracted';
/** The reader may still change the document: not confirmed, not read, not being read. */
export const isEditable = (doc: Pick<BidDocument, 'confirmed' | 'run' | 'status'>): boolean =>
  !doc.confirmed && !isExtracted(doc) && doc.status !== 'extracting';

export type Tone = 'positive' | 'notice' | 'negative' | 'info' | 'neutral';
export interface Light { tone: Tone; text: string }

/** The status light of a document row. */
export function docLight(doc: BidDocument, playbook: BidPlaybook | undefined): Light {
  if (doc.status === 'failed') return { tone: 'negative', text: 'Could not read' };
  if (doc.status === 'extracting') return { tone: 'info', text: 'Reading' };
  if (isExtracted(doc)) return { tone: 'positive', text: 'Read' };
  const gaps = gapsOf(doc, playbook);
  if (doc.confirmed) return gaps.length ? { tone: 'negative', text: `Needs ${gaps[0]}` } : { tone: 'positive', text: 'Confirmed' };
  return gaps.length ? { tone: 'notice', text: `Check: ${gaps[0]}` } : { tone: 'info', text: 'Ready to confirm' };
}

/** Who suggested the type, in words: "Suggested by the model", "Suggested by rules", "Changed by you". */
export function suggestedBy(doc: Pick<BidDocument, 'playbook' | 'proposed'>): string {
  if (doc.playbook !== doc.proposed.playbook) return 'Changed by you';
  return doc.proposed.by === 'model' ? 'Suggested by the model' : 'Suggested by rules';
}

/** Whether the document can be confirmed with what the model or the rules suggested, as it stands. */
export function canAccept(doc: BidDocument, playbook: BidPlaybook | undefined): boolean {
  return isEditable(doc) && !!playbook && gapsOf(doc, playbook).length === 0;
}

export type DocFilter = 'all' | 'review' | 'confirmed' | 'problems';

export function isProblem(doc: BidDocument, playbook: BidPlaybook | undefined): boolean {
  return doc.status === 'failed' || (isEditable(doc) && gapsOf(doc, playbook).length > 0);
}

export function inFilter(filter: DocFilter, doc: BidDocument, playbook: BidPlaybook | undefined): boolean {
  switch (filter) {
    case 'review': return isEditable(doc) && doc.status !== 'failed';
    case 'confirmed': return doc.confirmed;
    case 'problems': return isProblem(doc, playbook);
    default: return true;
  }
}

/** The "Counts as" and "Shared outside" of a type, as the playbook says them. */
export function sharedLabel(playbook: Pick<BidPlaybook, 'visibility'> | undefined): string {
  if (!playbook) return '';
  return playbook.visibility === 'internal' ? 'No, internal' : 'Yes';
}

// ---- speakers ----

export const isPlaced = (side: SpeakerSide | undefined): side is 'buyer' | 'ours' | 'other' => side === 'buyer' || side === 'ours' || side === 'other';

/** The sides the reader has chosen so far for the speakers of a call, by speaker id; "unknown" counts as not chosen. */
export interface SideDraft { side: SpeakerSide; acts_for: string }
export type SpeakerDraft = Record<string, SideDraft>;

export function draftOf(speakers: BidSpeaker[]): SpeakerDraft {
  return Object.fromEntries(speakers.map((s) => [s.id, { side: isPlaced(s.side) ? s.side : '', acts_for: s.acts_for ?? '' } as SideDraft]));
}

/** The people with no side yet. */
export const openSpeakers = (speakers: BidSpeaker[], draft: SpeakerDraft): BidSpeaker[] => speakers.filter((s) => !isPlaced(draft[s.id]?.side));

/** The draft with every open speaker put on the side that was suggested for them (where there is a suggestion). */
export function withSuggestions(speakers: BidSpeaker[], draft: SpeakerDraft): SpeakerDraft {
  const next = { ...draft };
  for (const s of speakers) {
    if (!isPlaced(next[s.id]?.side) && isPlaced(s.proposed)) next[s.id] = { side: s.proposed, acts_for: s.acts_for ?? '' };
  }
  return next;
}

/** How many people were put on a side other than the one suggested. */
export const changedSides = (speakers: BidSpeaker[], draft: SpeakerDraft): number =>
  speakers.filter((s) => isPlaced(draft[s.id]?.side) && isPlaced(s.proposed) && draft[s.id].side !== s.proposed).length;

/** The body of the PATCH that confirms the speakers of a call. */
export function speakersBody(speakers: BidSpeaker[], draft: SpeakerDraft) {
  return speakers.map((s) => {
    const d = draft[s.id] ?? { side: '' as SpeakerSide, acts_for: '' };
    return { id: s.id, name: s.name, side: d.side, acts_for: d.side === 'other' ? d.acts_for : '' };
  });
}

// ---- the steps of the wizard ----

export type Step = 'details' | 'documents' | 'speakers' | 'review' | 'run';
export const STEP_ORDER: Step[] = ['details', 'documents', 'speakers', 'review', 'run'];
export const STEP_TITLE: Record<Step, string> = { details: 'Bid details', documents: 'Documents', speakers: 'Call speakers', review: 'Review and start', run: 'Extraction' };

export interface StepInfo { key: Step; title: string; sub: string; state: 'done' | 'current' | 'todo' | 'skipped'; enabled: boolean }
export interface Wizard { steps: StepInfo[]; canNext: boolean; blocker: string; summary: string; hasCalls: boolean }

/** The confirmed documents that are calls. */
export const callsOf = (bid: Pick<Bid, 'documents' | 'playbooks'> | null): BidDocument[] =>
  bid ? bid.documents.filter((d) => d.confirmed && !!playbookOf(bid, d)?.spoken) : [];

/**
 * What the rail shows and the footer allows. `pending` is the number of files still going up;
 * `job` is the extraction of this bid, if one was started in this session.
 */
export function wizard(i: { step: Step; bid: Bid | null; name: string; customer: string; due: string | null; pending: number; job: ExtractJob | null }): Wizard {
  const { step, bid, pending, job } = i;
  const docs = bid?.documents ?? [];
  const confirmed = docs.filter((d) => d.confirmed);
  const calls = callsOf(bid);
  // A call whose speakers were found but not confirmed holds the reader back; one whose speakers could not be read does not (the Review step says so).
  const callsOpen = calls.filter((d) => !speakersUnread(d) && !d.speakers_confirmed);
  const detailsOk = !!i.name.trim();
  const docsOk = confirmed.length > 0 && pending === 0 && confirmed.every((d) => gapsOf(d, bid ? playbookOf(bid, d) : undefined).length === 0);
  const speakersOk = callsOpen.length === 0;
  const unread = calls.filter(speakersUnread).length;
  const started = !!job;
  const finished = job?.status === 'done';

  const at = STEP_ORDER.indexOf(step);
  const sub: Record<Step, string> = {
    details: detailsOk ? [i.customer.trim(), i.due ? `due ${dateLabel(i.due)}` : ''].filter(Boolean).join(' · ') || i.name.trim() : 'Name, customer, team',
    documents: docs.length ? `${confirmed.length} of ${docs.length} confirmed` : 'Upload and check each one',
    speakers: calls.length === 0 ? 'No calls in this bid'
      : `${calls.filter((d) => d.speakers_confirmed).length} of ${calls.length} calls confirmed${unread ? ` · ${unread} not read` : ''}`,
    review: started ? 'Started' : 'Order, plan, start',
    run: finished ? 'Finished' : job?.status === 'failed' ? 'Failed' : started ? 'Running' : 'Not started',
  };
  const ok: Record<Step, boolean> = { details: detailsOk, documents: docsOk, speakers: calls.length > 0 && speakersOk && unread === 0, review: started, run: finished };
  const steps = STEP_ORDER.map((key, n): StepInfo => ({
    key,
    title: STEP_TITLE[key],
    sub: sub[key],
    state: key === step ? 'current' : key === 'speakers' && calls.length === 0 && n < at ? 'skipped' : n < at || ok[key] ? 'done' : 'todo',
    enabled: key === 'run' ? started : started ? n < STEP_ORDER.indexOf('run') : n <= at || STEP_ORDER.slice(0, n).every((k) => ok[k] || (k === 'speakers' && calls.length === 0)),
  }));

  let blocker = '';
  if (step === 'details' && !detailsOk) blocker = 'Add a bid name to continue.';
  if (step === 'documents') {
    if (pending) blocker = `Reading ${pending} ${pending === 1 ? 'document' : 'documents'}...`;
    else if (!confirmed.length) blocker = docs.length ? 'Confirm at least one document to continue.' : 'Add the RFP and anything that came with it.';
    else if (!docsOk) blocker = 'A confirmed document is missing its issue date or number.';
  }
  if (step === 'speakers' && !speakersOk) blocker = `Confirm the speakers of ${callsOpen.length === 1 ? 'the call' : `${callsOpen.length} calls`}.`;
  const canNext = step === 'details' ? detailsOk : step === 'documents' ? docsOk : step === 'speakers' ? speakersOk : false;
  const unconfirmed = docs.length - confirmed.length;
  const summary = step === 'documents' && confirmed.length && unconfirmed && !blocker
    ? `${unconfirmed} unconfirmed ${unconfirmed === 1 ? 'document is' : 'documents are'} left out of this run.` : '';
  return { steps, canNext, blocker, summary, hasCalls: calls.length > 0 };
}

// ---- a run ----

/** The step names a reader sees. */
export const STEP_NAMES: Record<string, string> = {
  cut: 'Cut into units', extract: 'Label the units and build facts', relate: 'Link to earlier documents', save: 'Save the result',
  group: 'Group repeated points', pairs: 'Check facts that disagree', build: 'Build the fact list',
};

const DOC_STEPS = 4;
/** The steps of the whole bid that a reader sees (the server also reports a `plan` step, which is not one of them). */
export const BID_STEPS = ['group', 'pairs', 'build'];
const BID_STEP_COUNT = BID_STEPS.length;

const latestSteps = (steps: JobStep[]): JobStep[] => {
  const seen = new Map<string, JobStep>();
  for (const s of steps) seen.set(`${s.doc_no}/${s.step}`, s);
  return [...seen.values()];
};

export type RunState = 'done' | 'failed' | 'running' | 'waiting';

/** Where one document of the job stands: finished when it is saved or a stored result was reused; failed when a step failed. */
export function docRunState(steps: JobStep[], no: number): RunState {
  const own = latestSteps(steps).filter((s) => s.doc_no === no);
  if (!own.length) return 'waiting';
  if (own.some((s) => s.status === 'failed')) return 'failed';
  if (own.some((s) => (s.step === 'save' && s.status === 'done') || (s.step === 'extract' && s.status === 'reused'))) return 'done';
  return 'running';
}

/** Finished steps over expected steps, 0 to 1: four for each document read and three for the whole bid. */
export function jobProgress(steps: JobStep[], docNos: number[]): number {
  const total = docNos.length * DOC_STEPS + BID_STEP_COUNT;
  const finished = (s: JobStep) => s.status === 'done' || s.status === 'reused';
  const all = latestSteps(steps);
  let done = 0;
  for (const no of docNos) {
    const state = docRunState(steps, no);
    done += state === 'done' ? DOC_STEPS : Math.min(DOC_STEPS - 1, all.filter((s) => s.doc_no === no && finished(s)).length);
  }
  done += Math.min(BID_STEP_COUNT, all.filter((s) => s.doc_no === 0 && BID_STEPS.includes(s.step) && finished(s)).length);
  return total === 0 ? 0 : Math.min(1, done / total);
}

/** The step that is running now, as "Label the units and build facts, d2 call.json"; empty when none. */
export function runningNow(steps: JobStep[], files: Map<number, string>): string {
  const s = latestSteps(steps).filter((x) => x.status === 'running').pop();
  if (!s) return '';
  return `${STEP_NAMES[s.step] ?? s.step}${s.doc_no ? `, d${s.doc_no} ${files.get(s.doc_no) ?? ''}`.trimEnd() : ''}`;
}

export const clock = (seconds: number): string => {
  const t = Math.max(0, Math.round(seconds));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
};
