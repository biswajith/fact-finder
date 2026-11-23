// Pure helpers for the Documents page: what a playbook means for a reader, what is missing, in what order to show rows.
import type { Bid, BidDocument, BidPlan, BidPlaybook, JobStep } from './types';

/** "Level 1 · buyer document" and so on, from the playbook's level; empty for an unknown playbook. */
export function levelLabel(playbook: Pick<BidPlaybook, 'level'> | null | undefined): string {
  switch (playbook?.level) {
    case '1': return 'Level 1 · buyer document';
    case 'by speaker': return 'Level 2/3 · by speaker';
    case '4': return 'Level 4 · deal notes';
    default: return '';
  }
}

const PLAYBOOK_NAMES: Record<string, string> = {
  rfp: 'RFP',
  'reissued-rfp': 'Reissued RFP',
  'change-addendum': 'Change addendum',
  'qa-addendum': 'Q&A addendum',
  'fill-in-template': 'Fill-in template',
  'call-transcript': 'Call transcript',
  'deal-notes': 'Deal notes',
};

/** The name of a playbook as a reader says it ("deal-notes" is "Deal notes"); a name not listed is shown as it is. */
export function playbookLabel(name: string | null | undefined): string {
  return name ? PLAYBOOK_NAMES[name] ?? name : '';
}

const WORDS: Record<string, string> = {
  'type not confirmed': 'confirm the type',
  'issue date missing': 'add the issue date',
  'issue number missing': 'add the issue number',
  'speakers not confirmed': 'confirm the speakers',
  'a speaker has no side': 'choose a side for every speaker',
  'previous version not chosen': 'choose the document it replaces',
};

/** The server's short reasons in plain words, as one sentence; empty when nothing is missing. */
export function missingWords(missing: string[]): string {
  if (!missing.length) return '';
  const words = missing.map((m) => WORDS[m] ?? m);
  const text = words.join('; ');
  return `To do: ${text}.`;
}

/** A speaker's side as a reader says it: "Buyer", "Our side", "Other party"; empty for none or not decided. */
export function sideLabel(side: string | null | undefined): string {
  switch (side) {
    case 'buyer': return 'Buyer';
    case 'ours': return 'Our side';
    case 'other': return 'Other party';
    default: return '';
  }
}

/** The bid's documents in issue order; a document the order does not name goes last, by number. */
export function rowsInOrder(bid: Pick<Bid, 'documents' | 'order'>): BidDocument[] {
  const byId = new Map(bid.documents.map((d) => [d.doc_id, d]));
  const listed = new Set<string>();
  const out: BidDocument[] = [];
  for (const id of bid.order ?? []) {
    const d = byId.get(id);
    if (d && !listed.has(id)) {
      listed.add(id);
      out.push(d);
    }
  }
  const rest = bid.documents.filter((d) => !listed.has(d.doc_id)).sort((a, b) => a.no - b.no);
  return [...out, ...rest];
}

/** Whether the type and the fields it needs are filled in, so that Confirm may be pressed. */
export function canConfirm(
  doc: Pick<BidDocument, 'issue_number' | 'issue_date' | 'previous'> & { playbook?: string },
  playbook: Pick<BidPlaybook, 'name' | 'role'> | null | undefined,
): boolean {
  if (!playbook) return false;
  if (playbook.role === 'change' && !doc.issue_number) return false;
  if ((playbook.role === 'change' || playbook.role === 'context') && !doc.issue_date) return false;
  if (playbook.name === 'reissued-rfp' && !doc.previous) return false;
  return true;
}

export interface StepGroup {
  /** 0 for the whole bid. */
  no: number;
  title: string;
  steps: JobStep[];
}

const BID_STEPS = ['group', 'pairs', 'build'];

/** The job's steps grouped by document in the order of `docs`, then the whole-bid steps. The last report of a step wins. */
export function stepsByDocument(steps: JobStep[], docs: Pick<BidDocument, 'no' | 'file_name'>[]): StepGroup[] {
  const latest = (list: JobStep[]) => {
    const seen = new Map<string, JobStep>();
    for (const s of list) seen.set(s.step, s);
    return [...seen.values()];
  };
  const groups: StepGroup[] = [];
  for (const d of docs) {
    const own = steps.filter((s) => s.doc_no === d.no);
    if (own.length) groups.push({ no: d.no, title: `d${d.no} ${d.file_name}`, steps: latest(own) });
  }
  const whole = latest(steps.filter((s) => s.doc_no === 0 && BID_STEPS.includes(s.step)));
  if (whole.length) groups.push({ no: 0, title: 'Whole bid', steps: whole });
  return groups;
}

/** How many documents the next extraction reads: those in the plan with nothing missing. */
export function extractCount(plan: Pick<BidPlan, 'documents'> | null | undefined): number {
  return (plan?.documents ?? []).filter((d) => d.missing.length === 0).length;
}

/** "512 KB", "1.4 MB": a file size for a list of chosen files. */
export function fileSizeLabel(bytes: number): string {
  const kb = Math.max(bytes > 0 ? 1 : 0, Math.round(bytes / 1024));
  if (kb < 1024) return `${kb} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Whether "Our team" matters: only a call transcript has speakers to place on a side. */
export function showTeam(bid: Pick<Bid, 'documents'>): boolean {
  return bid.documents.some((d) => d.playbook === 'call-transcript');
}

/** Whether "Order of precedence" matters: two or more buyer (level 1) documents that could disagree. */
export function showPrecedence(bid: Pick<Bid, 'documents' | 'playbooks'>): boolean {
  return bid.documents.filter((d) => bid.playbooks.find((p) => p.name === d.playbook)?.level === '1').length >= 2;
}
