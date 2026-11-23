// What the facts and conflicts pages need to show a bid: its documents, levels, relations and what an option changes.
// Pure functions, tested in bidView.test.ts. `useBidDocs` (bidDocs.ts) reads the documents GET /facts returns for a bid.
import type { Citation, ConflictChange, ConflictOption, Fact, FactsDocument, RelationKind } from './types';

/** In a bid exactly when GET /facts listed documents. A single-document run has none. */
export interface BidDocs {
  inBid: boolean;
  docs: FactsDocument[];
  byNo: Map<number, FactsDocument>;
  byId: Map<string, FactsDocument>;
}

export function bidDocs(documents: FactsDocument[] | undefined): BidDocs {
  const docs = documents ?? [];
  return { inBid: docs.length > 0, docs, byNo: new Map(docs.map((d) => [d.no, d])), byId: new Map(docs.map((d) => [d.doc_id, d])) };
}

// ---- Levels ----

export const LEVEL_CHIP: Record<number, string> = {
  1: 'L1 · Buyer document',
  2: 'L2 · Buyer on a call',
  3: 'L3 · Our side on a call',
  4: 'L4 · Deal notes',
};
export const levelChip = (level: number | undefined): string => LEVEL_CHIP[level ?? 0] ?? '';

// ---- Citations ----

export const citeDoc = (c: Citation, d: BidDocs): FactsDocument | undefined =>
  (c.doc_id ? d.byId.get(c.doc_id) : undefined) ?? (c.doc_no ? d.byNo.get(c.doc_no) : undefined);

/** The page or time of a citation as the chip shows it: "p.4", or "00:04:12" for a spoken source. */
const where = (c: Citation): string => c.page_label || (c.page ? String(c.page) : '');

/** "d2 · p.4", or "d1 · 00:04:12 · Dana Whitcomb" when a speaker is named. */
export function citeLabel(c: Citation, d: BidDocs): string {
  const no = citeDoc(c, d)?.no ?? c.doc_no ?? 0;
  const at = where(c);
  const parts = [no ? `d${no}` : '', c.speaker ? at : at ? `p.${at}` : '', c.speaker ?? ''];
  return parts.filter(Boolean).join(' · ');
}

/** The tooltip of a chip: the file name of its document. */
export const citeTitle = (c: Citation, d: BidDocs): string => citeDoc(c, d)?.file_name ?? c.doc_id ?? '';

export const isInternal = (c: Citation): boolean => c.visibility === 'internal';

/** A fact whose every citation is an internal source: left out of the CSV to share. */
export const internalOnly = (f: Fact): boolean => f.citations.length > 0 && f.citations.every(isInternal);

// ---- Replaced facts and relations ----

export type ReplacedState = { kind: 'by'; id: string } | { kind: 'removed' } | { kind: 'plain' } | null;

/** How to say a fact is no longer current; null when it is current. */
export function replacedState(f: Fact): ReplacedState {
  if (!f.flags.includes('replaced')) return null;
  if (f.replaced_by) return { kind: 'by', id: f.replaced_by };
  const removed = (f.relations ?? []).some((r) => r.kind === 'REMOVES' && !r.rejected && r.to.fact_id === f.fact_id);
  return removed ? { kind: 'removed' } : { kind: 'plain' };
}

const FROM_WORDS: Record<RelationKind, string> = {
  REPLACES: 'Replaces', REMOVES: 'Removes', ADDS: 'Adds to', CLARIFIES: 'Clarifies', CONFIRMS: 'Confirms', DISAGREES: 'Disagrees with',
};
const TO_WORDS: Record<RelationKind, string> = {
  REPLACES: 'Replaced by', REMOVES: 'Removed by', ADDS: 'Added to by', CLARIFIES: 'Clarified by', CONFIRMS: 'Confirmed by', DISAGREES: 'Disagrees with',
};

export interface RelationLine {
  id: string;
  words: string;
  /** The fact at the other end, or "" when the relation points at a unit no fact stands on. */
  otherFactId: string;
  /** The other end's document and unit, for when there is no fact to name. */
  otherDocId: string;
  otherUnit: string;
}

/** Each live relation of a fact, worded from its point of view. A relation shared by two targets shows once per other end. */
export function relationLines(f: Fact): RelationLine[] {
  const out: RelationLine[] = [];
  const seen = new Set<string>();
  for (const r of f.relations ?? []) {
    if (r.rejected) continue;
    const fromHere = r.from.fact_id === f.fact_id;
    const other = fromHere ? r.to : r.from;
    const key = `${r.id}|${other.fact_id}|${other.doc_id}|${other.unit}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id: r.id, words: (fromHere ? FROM_WORDS : TO_WORDS)[r.kind] ?? r.kind,
      otherFactId: other.fact_id, otherDocId: other.doc_id, otherUnit: other.unit,
    });
  }
  return out;
}

// ---- Conflicts ----

const REASON_WORDS: Record<string, string> = {
  'user-edited fact replaced': 'A later document changes a fact you edited',
  'old value elsewhere': 'Another fact still states the old value',
  'depends on changed value': 'This fact may depend on a value that changed',
  'levels disagree': 'Sources at different levels disagree',
  'unfound target': 'A reference was not found in the earlier documents',
  'issued together': 'Two documents issued together disagree',
};
export const reasonWords = (reason: string | undefined): string => (reason ? REASON_WORDS[reason] ?? reason : '');

const clip = (s: string, n: number) => {
  const t = s.split(/\s+/).filter(Boolean).join(' ');
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

/** One line for a change an option makes. `ref` names a fact in words. */
export function describeEffect(c: ConflictChange, ref: (id: string) => string): string {
  if (c.op === 'delete') return `Deletes ${ref(c.fact_id)}`;
  if (c.add_flag === 'replaced') return `Marks ${ref(c.fact_id)} replaced`;
  if (c.add_flag) return `Adds the flag "${c.add_flag}" to ${ref(c.fact_id)}`;
  const f = c.fields ?? {};
  if (typeof f.text === 'string') return `Changes the text to "${clip(f.text, 120)}"`;
  if (Array.isArray(f.flags) && f.flags.includes('replaced')) return `Marks ${ref(c.fact_id)} replaced`;
  const parts = Object.entries(f).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`);
  return `Changes ${ref(c.fact_id)}${parts.length ? ` (${parts.join('; ')})` : ''}`;
}

/** What an option of a document conflict does, as short lines; "No change" when it does nothing. */
export function optionEffects(o: ConflictOption, ref: (id: string) => string): string[] {
  return o.changes.length ? o.changes.map((c) => describeEffect(c, ref)) : ['No change'];
}
